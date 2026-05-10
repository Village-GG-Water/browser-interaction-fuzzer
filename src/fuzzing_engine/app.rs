use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::time::{SystemTime, UNIX_EPOCH};

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

use super::clients::{DomGeneratorClient, DomGeneratorConfig, SimulatorClient, SimulatorConfig};
use super::config::AppConfig;
use super::corpus::{CorpusSeed, CorpusStore, SeedMetadata};
use super::coverage::CoverageTracker;
use super::executor::{ExecutionOutcome, TestcaseExecutor, save_crash_artifacts};
use super::input::{DocumentSpec, FuzzInput};
use super::metrics::RunMetrics;
use super::mutation::{DefaultMutationStrategy, MutationStrategy};
use super::reporting::Reporter;
use super::{EngineResult, engine_error};

pub struct FuzzingApp {
    config: AppConfig,
    corpus: CorpusStore,
    rng: StdRng,
    metrics: RunMetrics,
    stop_requested: Arc<AtomicBool>,
}

impl FuzzingApp {
    pub fn new(config: AppConfig) -> EngineResult<Self> {
        config.ensure_dirs()?;
        let corpus = CorpusStore::new(config.corpus_dir.clone());
        Ok(Self {
            config,
            corpus,
            rng: StdRng::from_entropy(),
            metrics: RunMetrics::default(),
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
        let mut generator = DomGeneratorClient::spawn(&generator_config)?;
        let simulator = SimulatorClient::spawn(&SimulatorConfig::from_app_config(&self.config))?;
        let mut executor = TestcaseExecutor::new(
            simulator,
            self.config.sancov_dir.clone(),
            self.config.asan_dir.clone(),
        );
        let strategy = DefaultMutationStrategy::new();
        let mut coverage = CoverageTracker::new();

        let mut seeds = self.load_or_create_initial_seeds(&mut generator, &strategy)?;
        self.metrics.corpus_size = seeds.len();

        let mut iteration = 0_u64;
        loop {
            if self.should_stop(iteration) {
                break;
            }
            iteration += 1;

            let seed_idx = self.rng.gen_range(0..seeds.len());
            let input = self.prepare_iteration_input(
                iteration,
                &seeds[seed_idx],
                &strategy,
                &mut generator,
            )?;

            let outcome = match executor.run(iteration, &input, &mut coverage) {
                Ok(outcome) => outcome,
                Err(error) => {
                    self.metrics.infra_errors += 1;
                    eprintln!("[executor] iteration {iteration} failed: {error}");
                    continue;
                }
            };

            self.record_outcome(iteration, &input, outcome, &mut seeds)?;

            if self.metrics.iterations % 10 == 0 {
                Reporter::progress(&self.metrics);
            }
        }

        let _ = generator.shutdown();
        Reporter::summary(&self.metrics);
        Ok(())
    }

    fn load_or_create_initial_seeds(
        &mut self,
        generator: &mut DomGeneratorClient,
        strategy: &DefaultMutationStrategy,
    ) -> EngineResult<Vec<CorpusSeed>> {
        let mut seeds = self.corpus.load_all()?;
        for seed in &seeds {
            Reporter::seed_loaded(&seed.spec.seed_id, &seed.metadata.source_kind);
        }

        while seeds.len() < self.config.seed_inputs {
            let seed_id = self.corpus.next_seed_id("seed_generated_")?;
            let seed_dir = self.create_generated_seed(&seed_id, generator, strategy)?;
            Reporter::generated_seed(&seed_id);
            seeds.push(self.corpus.load_seed(&seed_dir)?);
        }

        if seeds.is_empty() {
            return Err(engine_error("no corpus seeds available"));
        }
        Ok(seeds)
    }

    fn create_generated_seed(
        &mut self,
        seed_id: &str,
        generator: &mut DomGeneratorClient,
        strategy: &DefaultMutationStrategy,
    ) -> EngineResult<PathBuf> {
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
        let metadata = SeedMetadata {
            schema_version: 1,
            seed_id: seed_id.to_string(),
            created_at: unix_timestamp_string(),
            source_kind,
            generator_version: "dom-generator-v1".to_string(),
            coverage_edges: None,
            crash_summary: None,
        };
        self.corpus.write_seed(
            seed_id,
            DocumentSpec::Fdir {
                path: fdir_path.clone(),
            },
            &actions,
            &metadata,
            Some(&snapshot_path),
            Some(&fdir_path),
        )
    }

    fn prepare_iteration_input(
        &mut self,
        iteration: u64,
        seed: &CorpusSeed,
        strategy: &DefaultMutationStrategy,
        generator: &mut DomGeneratorClient,
    ) -> EngineResult<FuzzInput> {
        let work_dir = self
            .config
            .out_dir
            .join("iterations")
            .join(format!("{iteration:06}"));
        fs::create_dir_all(&work_dir)?;

        match &seed.input.document {
            DocumentSpec::Fdir { path } => {
                self.prepare_dom_input(iteration, seed, path, &work_dir, strategy, generator)
            }
            DocumentSpec::NoDocument { initial_url } => {
                let mut actions = seed.input.actions.clone();
                let plan = strategy.plan(&mut self.rng, false);
                if plan.mutate_actions {
                    strategy.mutate_actions(
                        &mut self.rng,
                        &mut actions,
                        self.config.max_actions,
                        &[],
                    );
                }
                Ok(FuzzInput {
                    seed_id: format!("{}_iter_{iteration:06}", seed.spec.seed_id),
                    seed_dir: work_dir,
                    document: DocumentSpec::NoDocument {
                        initial_url: initial_url.clone(),
                    },
                    actions,
                    snapshot_path: None,
                })
            }
        }
    }

    fn prepare_dom_input(
        &mut self,
        iteration: u64,
        seed: &CorpusSeed,
        source_fdir: &Path,
        work_dir: &Path,
        strategy: &DefaultMutationStrategy,
        generator: &mut DomGeneratorClient,
    ) -> EngineResult<FuzzInput> {
        let output_fdir = work_dir.join("document.fdir");
        let snapshot_path = work_dir.join("snapshot.html");
        let plan = strategy.plan(&mut self.rng, true);

        let doc = if plan.refresh_document {
            generator.generate_document(Some(&output_fdir))?
        } else if plan.dom_ops.is_empty() {
            fs::copy(source_fdir, &output_fdir)?;
            generator.load_document(&output_fdir)?
        } else {
            generator.mutate_document(source_fdir, &output_fdir, &plan.dom_ops)?
        };

        fs::write(&snapshot_path, &doc.html)?;
        let mut actions = seed.input.actions.clone();
        let interactables = doc.interactables;
        if plan.mutate_actions {
            strategy.mutate_actions(
                &mut self.rng,
                &mut actions,
                self.config.max_actions,
                &interactables,
            );
        }
        if actions.is_empty() {
            actions = strategy.initial_actions(
                &mut self.rng,
                self.config.seed_actions,
                &interactables,
                &doc.action_hints,
            );
        }

        Ok(FuzzInput {
            seed_id: format!("{}_iter_{iteration:06}", seed.spec.seed_id),
            seed_dir: work_dir.to_path_buf(),
            document: DocumentSpec::Fdir { path: output_fdir },
            actions,
            snapshot_path: Some(snapshot_path),
        })
    }

    fn record_outcome(
        &mut self,
        iteration: u64,
        input: &FuzzInput,
        outcome: ExecutionOutcome,
        seeds: &mut Vec<CorpusSeed>,
    ) -> EngineResult<()> {
        let response = &outcome.response;
        self.metrics.record_iteration(
            input.actions.len(),
            response.actions_succeeded,
            response.selector_fallbacks,
            response.slow_actions,
            response.timings,
        );

        if outcome.new_coverage_edges > 0 {
            let seed_id = self.corpus.next_seed_id("seed_cov_")?;
            let metadata = SeedMetadata {
                schema_version: 1,
                seed_id: seed_id.clone(),
                created_at: unix_timestamp_string(),
                source_kind: "coverage".to_string(),
                generator_version: "dom-generator-v1".to_string(),
                coverage_edges: Some(outcome.new_coverage_edges as u64),
                crash_summary: None,
            };
            let seed_dir = self.corpus.write_seed(
                &seed_id,
                input.document.clone(),
                &input.actions,
                &metadata,
                input.html_path(),
                document_path_for_copy(input).as_deref(),
            )?;
            seeds.push(self.corpus.load_seed(&seed_dir)?);
            self.metrics.corpus_size = seeds.len();
            self.metrics.new_coverage_inputs += 1;
            Reporter::new_coverage(&seed_id, outcome.new_coverage_edges);
        }

        if outcome.is_crash() {
            self.metrics.crashes += 1;
            let case_dir = save_crash_artifacts(
                &self.config.crash_dir,
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

fn document_path_for_copy(input: &FuzzInput) -> Option<PathBuf> {
    match &input.document {
        DocumentSpec::Fdir { path } => Some(path.clone()),
        DocumentSpec::NoDocument { .. } => None,
    }
}

fn unix_timestamp_string() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("unix:{seconds}")
}
