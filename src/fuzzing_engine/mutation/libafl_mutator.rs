use std::borrow::Cow;
use std::fs;
use std::path::PathBuf;

use libafl::Error;
use libafl::corpus::CorpusId;
use libafl::mutators::{MutationResult, Mutator};
use libafl::state::HasRand;
use libafl_bolts::Named;
use libafl_bolts::rands::Rand;
use rand::SeedableRng;
use rand::rngs::StdRng;

use super::{DefaultMutationStrategy, MutationStrategy};
use crate::fuzzing_engine::clients::{DomGeneratorClient, DomGeneratorConfig};
use crate::fuzzing_engine::input::{DocumentSpec, FuzzInput};

pub struct LibAflMutationAdapter {
    generator: DomGeneratorClient,
    strategy: DefaultMutationStrategy,
    out_dir: PathBuf,
    max_actions: usize,
    seed_actions: usize,
    counter: u64,
}

impl LibAflMutationAdapter {
    pub fn new(
        generator_config: &DomGeneratorConfig,
        out_dir: PathBuf,
        max_actions: usize,
        seed_actions: usize,
    ) -> Result<Self, Error> {
        let generator = DomGeneratorClient::spawn(generator_config).map_err(|error| {
            Error::unknown(format!("failed to spawn mutation generator: {error}"))
        })?;
        Ok(Self {
            generator,
            strategy: DefaultMutationStrategy::new(),
            out_dir,
            max_actions,
            seed_actions,
            counter: 0,
        })
    }

    fn next_work_dir(&mut self) -> Result<PathBuf, Error> {
        self.counter += 1;
        let dir = self
            .out_dir
            .join("libafl_mutations")
            .join(format!("{:06}", self.counter));
        fs::create_dir_all(&dir)
            .map_err(|error| Error::unknown(format!("failed to create mutation dir: {error}")))?;
        Ok(dir)
    }
}

impl Named for LibAflMutationAdapter {
    fn name(&self) -> &Cow<'static, str> {
        static NAME: Cow<'static, str> = Cow::Borrowed("LibAflMutationAdapter");
        &NAME
    }
}

impl<S> Mutator<FuzzInput, S> for LibAflMutationAdapter
where
    S: HasRand,
{
    fn mutate(&mut self, state: &mut S, input: &mut FuzzInput) -> Result<MutationResult, Error> {
        let seed = state.rand_mut().next();
        let mut rng = StdRng::seed_from_u64(seed);
        let has_document = matches!(input.document, DocumentSpec::Fdir { .. });
        let plan = self.strategy.plan(&mut rng, has_document);
        let work_dir = self.next_work_dir()?;

        let mut mutated = false;
        match &input.document {
            DocumentSpec::Fdir { path } => {
                let output_fdir = work_dir.join("document.fdir");
                let snapshot_path = work_dir.join("snapshot.html");
                let doc = if plan.refresh_document {
                    mutated = true;
                    self.generator.generate_document(Some(&output_fdir))
                } else if plan.dom_ops.is_empty() {
                    fs::copy(path, &output_fdir).map_err(|error| {
                        Error::unknown(format!("failed to copy fdir for mutation: {error}"))
                    })?;
                    self.generator.load_document(&output_fdir)
                } else {
                    mutated = true;
                    self.generator
                        .mutate_document(path, &output_fdir, &plan.dom_ops)
                }
                .map_err(|error| Error::unknown(format!("DOM mutation failed: {error}")))?;

                fs::write(&snapshot_path, &doc.html).map_err(|error| {
                    Error::unknown(format!("failed to write snapshot: {error}"))
                })?;

                if plan.mutate_actions {
                    mutated |= self.strategy.mutate_actions(
                        &mut rng,
                        &mut input.actions,
                        self.max_actions,
                        &doc.interactables,
                    );
                }
                if input.actions.is_empty() {
                    input.actions = self.strategy.initial_actions(
                        &mut rng,
                        self.seed_actions,
                        &doc.interactables,
                        &doc.action_hints,
                    );
                    mutated = true;
                }

                input.seed_id = format!("{}_mut_{:06}", input.seed_id, self.counter);
                input.seed_dir = work_dir;
                input.document = DocumentSpec::Fdir { path: output_fdir };
                input.snapshot_path = Some(snapshot_path);
            }
            DocumentSpec::NoDocument { .. } => {
                if plan.mutate_actions {
                    mutated |= self.strategy.mutate_actions(
                        &mut rng,
                        &mut input.actions,
                        self.max_actions,
                        &[],
                    );
                }
                input.seed_id = format!("{}_mut_{:06}", input.seed_id, self.counter);
                input.seed_dir = work_dir;
            }
        }

        if mutated {
            Ok(MutationResult::Mutated)
        } else {
            Ok(MutationResult::Skipped)
        }
    }

    fn post_exec(&mut self, _state: &mut S, _new_corpus_id: Option<CorpusId>) -> Result<(), Error> {
        Ok(())
    }
}
