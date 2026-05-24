use std::cell::RefCell;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::num::NonZeroUsize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::rc::Rc;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use libafl::corpus::{Corpus, InMemoryCorpus, Testcase};
use libafl::events::NopEventManager;
use libafl::executors::ExitKind;
use libafl::feedback_or;
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
use super::lifecycle::{HAZARD_MAP, HAZARD_MAP_SIZE};
use super::metrics::RunMetrics;
use super::mutation::{
    DefaultMutationStrategy, LibAflMutationAdapter, MutationPhase, MutationPolicyState,
    MutationStrategy,
};
use super::reporting::Reporter;
use super::seed_store::{SeedInput, SeedMetadata, SeedStore};
use super::testcase_runner::{ExecutionOutcome, TestcaseRunner, save_crash_artifacts};
use super::{EngineResult, engine_error};

pub struct FuzzingApp {
    config: AppConfig,
    session_id: String,
    rng: StdRng,
    stop_requested: Arc<AtomicBool>,
}

impl FuzzingApp {
    pub fn new(config: AppConfig) -> EngineResult<Self> {
        config.ensure_dirs()?;
        Ok(Self {
            config,
            session_id: new_session_id(),
            rng: StdRng::from_entropy(),
            stop_requested: Arc::new(AtomicBool::new(false)),
        })
    }

    pub fn run(&mut self) -> EngineResult<()> {
        if self.config.should_run_managed_parallel() {
            return self.run_managed_parallel();
        }
        self.run_worker()
    }

    fn run_managed_parallel(&self) -> EngineResult<()> {
        Reporter::print_config(&self.config);
        let worker_count = self.config.parallel_workers;
        let exe = env::current_exe()?;
        let stop_requested = Arc::clone(&self.stop_requested);
        ctrlc::set_handler(move || {
            if stop_requested.swap(true, Ordering::SeqCst) {
                eprintln!("[signal] second Ctrl+C received, exiting immediately");
                std::process::exit(130);
            }
            eprintln!("[signal] Ctrl+C received, stopping managed workers");
        })?;

        let mut workers = Vec::new();
        for worker_id in 0..worker_count {
            workers.push(spawn_worker(&self.config, &exe, worker_id, worker_count)?);
        }

        println!("[parallel] launched {worker_count} workers");
        let mut remaining = workers.len();
        let mut stop_deadline = None;
        while remaining > 0 {
            if self.stop_requested.load(Ordering::SeqCst) {
                let deadline =
                    stop_deadline.get_or_insert_with(|| Instant::now() + Duration::from_secs(2));
                if Instant::now() >= *deadline {
                    for worker in workers.iter_mut().filter(|worker| worker.status.is_none()) {
                        eprintln!("[parallel] killing worker {}", worker.id);
                        let _ = worker.child.kill();
                    }
                }
            }

            for worker in workers.iter_mut().filter(|worker| worker.status.is_none()) {
                if let Some(status) = worker.child.try_wait()? {
                    println!("[parallel] worker {} exited with {status}", worker.id);
                    worker.status = Some(status);
                    remaining -= 1;
                }
            }

            if remaining > 0 {
                thread::sleep(Duration::from_millis(100));
            }
        }

        let mut failed = Vec::new();
        for mut worker in workers {
            if let Some(thread) = worker.stdout_thread.take() {
                let _ = thread.join();
            }
            if let Some(thread) = worker.stderr_thread.take() {
                let _ = thread.join();
            }
            let Some(status) = worker.status else {
                failed.push(worker.id);
                continue;
            };
            if !status.success() {
                failed.push(worker.id);
            }
        }

        if failed.is_empty() {
            println!("[parallel] all workers completed successfully");
            Ok(())
        } else {
            Err(engine_error(format!("workers failed: {failed:?}")))
        }
    }

    fn run_worker(&mut self) -> EngineResult<()> {
        Reporter::print_config(&self.config);
        let crash_session_dir = self
            .config
            .crash_dir
            .join(format!("session_{}", self.session_id));
        fs::create_dir_all(&crash_session_dir)?;
        Reporter::session_started(&self.session_id, &crash_session_dir);
        self.install_ctrlc_handler()?;

        let generator_config = DomGeneratorConfig {
            generator_dir: self.config.dom_generator_dir.clone(),
            uv_cache_dir: self.config.uv_cache_dir.clone(),
        };
        let policy = Rc::new(RefCell::new(MutationPolicyState::new(
            self.config.max_actions,
        )));
        let mut seed_generator = DomGeneratorClient::spawn(&generator_config)?;
        let strategy = DefaultMutationStrategy::new();
        let seeds = self.load_or_create_initial_seeds(&mut seed_generator, &strategy, &policy)?;
        let _ = seed_generator.shutdown();

        let metrics = Rc::new(RefCell::new(RunMetrics::default()));
        {
            let mut metrics = metrics.borrow_mut();
            metrics.corpus_size = seeds.len();
            metrics.policy_snapshot = Some(policy.borrow().snapshot());
        }

        let simulator = SimulatorClient::spawn(&SimulatorConfig::from_app_config(&self.config))?;
        let mut testcase_runner = TestcaseRunner::new(
            simulator,
            self.config.sancov_dir.clone(),
            self.config.asan_dir.clone(),
        );
        let mut coverage = CoverageTracker::new();
        let crash_session_dir = crash_session_dir.clone();
        let session_id = self.session_id.clone();
        let harness_metrics = Rc::clone(&metrics);
        let harness_policy = Rc::clone(&policy);
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
                    if let Err(error) = record_outcome(
                        &session_id,
                        &crash_session_dir,
                        &mut metrics,
                        &harness_policy,
                        harness_iteration,
                        input,
                        outcome,
                    ) {
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
        let hazard_observer = unsafe {
            HitcountsMapObserver::new(StdMapObserver::from_mut_ptr(
                "lifecycle_hazard_map",
                std::ptr::addr_of_mut!(HAZARD_MAP) as *mut u8,
                HAZARD_MAP_SIZE,
            ))
        };

        let mut feedback = feedback_or!(
            MaxMapFeedback::with_name("sancov_feedback", &edges_observer),
            MaxMapFeedback::with_name("lifecycle_hazard_feedback", &hazard_observer)
        );
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
        let mut executor =
            PlainExecutor::new(harness, tuple_list!(edges_observer, hazard_observer));
        let mut stages = tuple_list!(StdMutationalStage::with_max_iterations(
            LibAflMutationAdapter::new(
                &generator_config,
                self.config.out_dir.clone(),
                self.config.max_actions,
                self.config.seed_actions,
                Rc::clone(&policy),
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
        policy: &Rc<RefCell<MutationPolicyState>>,
    ) -> EngineResult<Vec<SeedInput>> {
        let mut seeds = self.load_initial_seed_dir()?;
        for seed in &seeds {
            Reporter::seed_loaded(&seed.spec.seed_id, &seed.metadata.source_kind);
        }

        while seeds.len() < self.config.seed_inputs {
            let seed_id = format!("seed_generated_{:06}", seeds.len() + 1);
            let seed = self.create_generated_seed(&seed_id, generator, strategy, policy)?;
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
        let seeds = SeedStore::new(seed_dir.clone()).load_all()?;
        Ok(partition_worker_seeds(
            seeds,
            self.config.worker_id,
            self.config.worker_count,
        ))
    }

    fn create_generated_seed(
        &mut self,
        seed_id: &str,
        generator: &mut DomGeneratorClient,
        strategy: &DefaultMutationStrategy,
        policy: &Rc<RefCell<MutationPolicyState>>,
    ) -> EngineResult<SeedInput> {
        let work_dir = self.config.out_dir.join("seed_build").join(seed_id);
        fs::create_dir_all(&work_dir)?;
        let fdir_path = work_dir.join("document.fdir");
        let snapshot_path = work_dir.join("snapshot.html");
        let budget = policy.borrow().initial_generation_budget();
        let doc = generator.generate_document(Some(&fdir_path), Some(budget))?;
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
            interactables: doc.interactables,
            document_stats: Some(doc.stats),
            mutation_phase: None,
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
    session_id: &str,
    crash_session_dir: &Path,
    metrics: &mut RunMetrics,
    policy: &Rc<RefCell<MutationPolicyState>>,
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
        Reporter::new_coverage(iteration, outcome.new_coverage_edges);
    }
    if outcome.hazard_summary.has_new_boundary() {
        metrics.new_hazard_events += outcome.hazard_summary.new_boundaries.len() as u64;
        for boundary in &outcome.hazard_summary.new_boundaries {
            Reporter::new_hazard(
                iteration,
                boundary.as_str(),
                outcome.hazard_summary.stale_reuse_candidates,
            );
        }
    }
    metrics.last_stale_reuse_candidates = outcome.hazard_summary.stale_reuse_candidates;
    metrics.last_hazard_boundary = outcome
        .hazard_summary
        .last_boundary
        .map(|boundary| boundary.as_str().to_string());
    let phase = input
        .mutation_phase
        .as_deref()
        .and_then(MutationPhase::from_str);
    {
        let mut policy = policy.borrow_mut();
        policy.record_result(
            phase,
            outcome.new_coverage_edges > 0 || outcome.hazard_summary.has_new_boundary(),
        );
        metrics.policy_snapshot = Some(policy.snapshot());
    }

    if outcome.is_crash() {
        metrics.crashes += 1;
        let case_dir = save_crash_artifacts(
            session_id,
            crash_session_dir,
            iteration,
            input,
            &input.actions,
            response,
            &outcome.hazard_summary,
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

struct ManagedWorker {
    id: usize,
    child: Child,
    status: Option<ExitStatus>,
    stdout_thread: Option<JoinHandle<()>>,
    stderr_thread: Option<JoinHandle<()>>,
}

fn spawn_worker(
    config: &AppConfig,
    exe: &Path,
    worker_id: usize,
    worker_count: usize,
) -> EngineResult<ManagedWorker> {
    let out_dir = config.out_dir.join("workers").join(worker_id.to_string());
    let crash_dir = config.crash_dir.join("workers").join(worker_id.to_string());

    let mut command = Command::new(exe);
    command
        .current_dir(&config.workspace_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("WORKER_ID", worker_id.to_string())
        .env("WORKER_COUNT", worker_count.to_string())
        .env("PARALLEL_WORKERS", worker_count.to_string())
        .env("OUT_DIR", &out_dir)
        .env("CRASH_DIR", &crash_dir);

    if let Some(max_iterations) = config.max_iterations {
        let per_worker = max_iterations.div_ceil(worker_count as u64).max(1);
        command.env("MAX_ITERATIONS", per_worker.to_string());
    }

    let mut child = command
        .spawn()
        .map_err(|error| engine_error(format!("failed to spawn worker {worker_id}: {error}")))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| engine_error(format!("worker {worker_id} stdout was not piped")))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| engine_error(format!("worker {worker_id} stderr was not piped")))?;

    Ok(ManagedWorker {
        id: worker_id,
        child,
        status: None,
        stdout_thread: Some(prefix_worker_output(worker_id, "stdout", stdout)),
        stderr_thread: Some(prefix_worker_output(worker_id, "stderr", stderr)),
    })
}

fn prefix_worker_output<R>(worker_id: usize, stream_name: &'static str, stream: R) -> JoinHandle<()>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(stream);
        for line in reader.lines() {
            match line {
                Ok(line) if stream_name == "stderr" => {
                    eprintln!("[worker {worker_id} {stream_name}] {line}");
                }
                Ok(line) => {
                    println!("[worker {worker_id} {stream_name}] {line}");
                }
                Err(error) => {
                    eprintln!("[worker {worker_id} {stream_name}] read failed: {error}");
                    break;
                }
            }
        }
    })
}

fn partition_worker_seeds(
    seeds: Vec<SeedInput>,
    worker_id: Option<usize>,
    worker_count: usize,
) -> Vec<SeedInput> {
    let Some(worker_id) = worker_id else {
        return seeds;
    };
    if worker_count <= 1 {
        return seeds;
    }
    seeds
        .into_iter()
        .enumerate()
        .filter_map(|(index, seed)| (index % worker_count == worker_id).then_some(seed))
        .collect()
}

fn new_session_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("{millis}_{}", std::process::id())
}
