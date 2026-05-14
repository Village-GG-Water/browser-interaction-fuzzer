use std::cell::RefCell;
use std::fs;
use std::num::NonZeroUsize;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

use libafl::corpus::{Corpus, InMemoryCorpus, Testcase};
use libafl::events::NopEventManager;
use libafl::executors::ExitKind;
use libafl::feedbacks::{CrashFeedback, MaxMapFeedback};
use libafl::fuzzer::{Fuzzer, StdFuzzer};
use libafl::observers::{HitcountsMapObserver, StdMapObserver};
use libafl::schedulers::QueueScheduler;
use libafl::stages::mutational::StdMutationalStage;
use libafl::state::{HasCorpus, StdState};
use libafl_bolts::current_nanos;
use libafl_bolts::rands::StdRand;
use libafl_bolts::tuples::tuple_list;
use rand::SeedableRng;
use rand::rngs::StdRng;

use super::clients::{DomGeneratorClient, DomGeneratorConfig, SimulatorClient, SimulatorConfig};
use super::config::AppConfig;
use super::coverage::{COVERAGE_MAP, COVERAGE_MAP_SIZE, CoverageTracker};
use super::input::{DocumentSpec, FuzzInput};
use super::libafl_executor::PlainExecutor;
use super::metrics::RunMetrics;
use super::mutation::{DefaultMutationStrategy, LibAflMutationAdapter, MutationStrategy};
use super::reporting::Reporter;
use super::seed_store::{SeedInput, SeedMetadata, SeedStore};
use super::testcase_runner::{ExecutionOutcome, TestcaseRunner, save_crash_artifacts};
use super::{EngineResult, engine_error};

pub struct FuzzingApp {
    config: AppConfig,
    rng: StdRng,
    stop_requested: Arc<AtomicBool>,
}

impl FuzzingApp {
    pub fn new(config: AppConfig) -> EngineResult<Self> {
        config.ensure_dirs()?;
        Ok(Self {
            config,
            rng: StdRng::from_entropy(),
            stop_requested: Arc::new(AtomicBool::new(false)),
        })
    }

    pub fn run(&mut self) -> EngineResult<()> {
        Reporter::print_config(&self.config);
        self.install_ctrlc_handler()?;

        let generator_config = DomGeneratorConfig {
            generator_dir: self.config.dom_generator_dir.clone(),
            uv_cache_dir: self.config.uv_cache_dir.clone(),
        };
        let mut seed_generator = DomGeneratorClient::spawn(&generator_config)?;
        let strategy = DefaultMutationStrategy::new();
        let seeds = self.load_or_create_initial_seeds(&mut seed_generator, &strategy)?;
        let _ = seed_generator.shutdown();

        let metrics = Rc::new(RefCell::new(RunMetrics::default()));
        metrics.borrow_mut().corpus_size = seeds.len();

        let simulator = SimulatorClient::spawn(&SimulatorConfig::from_app_config(&self.config))?;
        let mut testcase_runner = TestcaseRunner::new(
            simulator,
            self.config.sancov_dir.clone(),
            self.config.asan_dir.clone(),
        );
        let mut coverage = CoverageTracker::new();
        let crash_dir = self.config.crash_dir.clone();
        let harness_metrics = Rc::clone(&metrics);
        let mut harness_iteration = 0_u64;

        let harness = move |input: &FuzzInput| -> ExitKind {
            harness_iteration += 1;
            match testcase_runner.run(harness_iteration, input, &mut coverage) {
                Ok(outcome) => {
                    let exit_kind = if outcome.is_crash() {
                        ExitKind::Crash
                    } else {
                        ExitKind::Ok
                    };
                    let mut metrics = harness_metrics.borrow_mut();
                    if let Err(error) =
                        record_outcome(&crash_dir, &mut metrics, harness_iteration, input, outcome)
                    {
                        metrics.infra_errors += 1;
                        eprintln!(
                            "[executor] failed to record iteration {harness_iteration}: {error}"
                        );
                    }
                    if metrics.iterations % 10 == 0 {
                        Reporter::progress(&metrics);
                    }
                    exit_kind
                }
                Err(error) => {
                    let mut metrics = harness_metrics.borrow_mut();
                    metrics.infra_errors += 1;
                    eprintln!("[executor] iteration {harness_iteration} failed: {error}");
                    ExitKind::Ok
                }
            }
        };

        let edges_observer = unsafe {
            HitcountsMapObserver::new(StdMapObserver::from_mut_ptr(
                "sancov_map",
                std::ptr::addr_of_mut!(COVERAGE_MAP) as *mut u8,
                COVERAGE_MAP_SIZE,
            ))
        };

        let mut feedback = MaxMapFeedback::new(&edges_observer);
        let mut objective = CrashFeedback::new();
        let rng = StdRand::with_seed(current_nanos());
        let mut state = StdState::new(
            rng,
            InMemoryCorpus::<FuzzInput>::new(),
            InMemoryCorpus::<FuzzInput>::new(),
            &mut feedback,
            &mut objective,
        )?;

        for seed in seeds {
            state.corpus_mut().add(Testcase::new(seed.input))?;
        }
        if state.corpus().count() == 0 {
            return Err(engine_error("no corpus seeds available"));
        }

        let scheduler = QueueScheduler::new();
        let mut fuzzer = StdFuzzer::new(scheduler, feedback, objective);
        let mut manager = NopEventManager::new();
        let mut executor = PlainExecutor::new(harness, tuple_list!(edges_observer));
        let mut stages = tuple_list!(StdMutationalStage::with_max_iterations(
            LibAflMutationAdapter::new(
                &generator_config,
                self.config.out_dir.clone(),
                self.config.max_actions,
                self.config.seed_actions,
            )?,
            NonZeroUsize::new(1).expect("1 is non-zero"),
        ));

        println!("[libafl] fuzzing started. Press Ctrl+C to stop.");
        while !self.should_stop(total_executions(&metrics.borrow())) {
            fuzzer.fuzz_one(&mut stages, &mut executor, &mut state, &mut manager)?;
            metrics.borrow_mut().corpus_size = state.corpus().count();
        }

        Reporter::summary(&metrics.borrow());
        Ok(())
    }

    fn load_or_create_initial_seeds(
        &mut self,
        generator: &mut DomGeneratorClient,
        strategy: &DefaultMutationStrategy,
    ) -> EngineResult<Vec<SeedInput>> {
        let mut seeds = self.load_initial_seed_dir()?;
        for seed in &seeds {
            Reporter::seed_loaded(&seed.spec.seed_id, &seed.metadata.source_kind);
        }

        while seeds.len() < self.config.seed_inputs {
            let seed_id = format!("seed_generated_{:06}", seeds.len() + 1);
            let seed = self.create_generated_seed(&seed_id, generator, strategy)?;
            Reporter::generated_seed(&seed_id);
            seeds.push(seed);
        }

        if seeds.is_empty() {
            return Err(engine_error("no corpus seeds available"));
        }
        Ok(seeds)
    }

    fn load_initial_seed_dir(&self) -> EngineResult<Vec<SeedInput>> {
        let Some(seed_dir) = &self.config.initial_seed_dir else {
            return Ok(Vec::new());
        };
        SeedStore::new(seed_dir.clone()).load_all()
    }

    fn create_generated_seed(
        &mut self,
        seed_id: &str,
        generator: &mut DomGeneratorClient,
        strategy: &DefaultMutationStrategy,
    ) -> EngineResult<SeedInput> {
        let work_dir = self.config.out_dir.join("seed_build").join(seed_id);
        fs::create_dir_all(&work_dir)?;
        let fdir_path = work_dir.join("document.fdir");
        let snapshot_path = work_dir.join("snapshot.html");
        let doc = generator.generate_document(Some(&fdir_path))?;
        fs::write(&snapshot_path, &doc.html)?;
        let actions = strategy.initial_actions(
            &mut self.rng,
            self.config.seed_actions,
            &doc.interactables,
            &doc.action_hints,
        );
        let source_kind = doc.id.clone().unwrap_or_else(|| "generated".to_string());
        let metadata = SeedMetadata { source_kind };
        let spec = super::input::TestcaseSpec {
            schema_version: 1,
            seed_id: seed_id.to_string(),
            document: DocumentSpec::Fdir {
                path: fdir_path.clone(),
            },
            interaction_scope: vec![
                super::input::InteractionScope::Dom,
                super::input::InteractionScope::BrowserUi,
            ],
            actions_path: PathBuf::from("actions.json"),
        };
        let input = FuzzInput {
            seed_id: seed_id.to_string(),
            seed_dir: work_dir,
            document: spec.document.clone(),
            actions,
            snapshot_path: Some(snapshot_path),
        };
        Ok(SeedInput {
            spec,
            metadata,
            input,
        })
    }

    fn install_ctrlc_handler(&self) -> EngineResult<()> {
        let stop_requested = Arc::clone(&self.stop_requested);
        ctrlc::set_handler(move || {
            if stop_requested.swap(true, Ordering::SeqCst) {
                eprintln!("[signal] second Ctrl+C received, exiting immediately");
                std::process::exit(130);
            }
            eprintln!("[signal] Ctrl+C received, stopping after current iteration");
        })?;
        Ok(())
    }

    fn should_stop(&self, completed_iterations: u64) -> bool {
        if self.stop_requested.load(Ordering::SeqCst) {
            return true;
        }
        if let Some(limit) = self.config.max_iterations {
            completed_iterations >= limit
        } else {
            false
        }
    }
}

fn record_outcome(
    crash_dir: &Path,
    metrics: &mut RunMetrics,
    iteration: u64,
    input: &FuzzInput,
    outcome: ExecutionOutcome,
) -> EngineResult<()> {
    let response = &outcome.response;
    metrics.record_iteration(
        input.actions.len(),
        response.actions_succeeded,
        response.selector_fallbacks,
        response.slow_actions,
        response.timings,
    );

    if outcome.new_coverage_edges > 0 {
        metrics.new_coverage_events += 1;
        Reporter::new_coverage(outcome.new_coverage_edges);
    }

    if outcome.is_crash() {
        metrics.crashes += 1;
        let case_dir = save_crash_artifacts(
            crash_dir,
            iteration,
            input,
            &input.actions,
            response,
            outcome.classified_crash.as_ref(),
        )?;
        let crash_name = outcome
            .crash_type()
            .map(|kind| kind.as_str())
            .unwrap_or("unknown");
        Reporter::crash(iteration, crash_name, &case_dir);
    }

    Ok(())
}

fn total_executions(metrics: &RunMetrics) -> u64 {
    metrics.iterations + metrics.infra_errors
}
