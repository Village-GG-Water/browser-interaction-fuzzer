use rand::Rng;

use super::action_ops::{
    InteractableMetadata, action_sequence_from_metadata, mutate_action_sequence,
};
use super::policy::{DomMutationBudget, MutationPhase};
use super::scheduler::{MutationPlan, MutationScheduler};
use crate::fuzzing_engine::actions::Action;
use crate::fuzzing_engine::input::DocumentStats;

pub trait MutationStrategy {
    fn initial_actions<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        seed_actions: usize,
        interactables: &[InteractableMetadata],
        action_hints: &[Action],
    ) -> Vec<Action>;

    fn plan<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        phase: MutationPhase,
        document_available: bool,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> MutationPlan;

    fn mutate_actions<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        actions: &mut Vec<Action>,
        max_actions: usize,
        interactables: &[InteractableMetadata],
    ) -> bool;
}

pub struct DefaultMutationStrategy {
    scheduler: MutationScheduler,
}

impl DefaultMutationStrategy {
    pub fn new() -> Self {
        Self {
            scheduler: MutationScheduler::new(),
        }
    }
}

impl MutationStrategy for DefaultMutationStrategy {
    fn initial_actions<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        seed_actions: usize,
        interactables: &[InteractableMetadata],
        action_hints: &[Action],
    ) -> Vec<Action> {
        action_sequence_from_metadata(rng, seed_actions, interactables, action_hints)
    }

    fn plan<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        phase: MutationPhase,
        document_available: bool,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> MutationPlan {
        self.scheduler
            .choose(rng, phase, document_available, stats, budget)
    }

    fn mutate_actions<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        actions: &mut Vec<Action>,
        max_actions: usize,
        interactables: &[InteractableMetadata],
    ) -> bool {
        mutate_action_sequence(rng, actions, max_actions, interactables)
    }
}
