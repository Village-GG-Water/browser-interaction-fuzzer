use rand::Rng;

use super::dom_ops::DomMutationOp;
use super::policy::{DomMutationBudget, MutationPhase};
use crate::fuzzing_engine::input::DocumentStats;

#[derive(Debug, Clone, Default)]
pub struct MutationPlan {
    pub phase: Option<MutationPhase>,
    pub dom_ops: Vec<DomMutationOp>,
    pub mutate_actions: bool,
    pub refresh_document: bool,
}

pub struct MutationScheduler {
    max_dom_ops_per_iteration: usize,
}

impl MutationScheduler {
    pub fn new() -> Self {
        Self {
            max_dom_ops_per_iteration: 3,
        }
    }

    pub fn choose<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        phase: MutationPhase,
        document_available: bool,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> MutationPlan {
        if !document_available || phase == MutationPhase::UserInteraction {
            return MutationPlan {
                phase: Some(MutationPhase::UserInteraction),
                dom_ops: Vec::new(),
                mutate_actions: true,
                refresh_document: false,
            };
        }

        MutationPlan {
            phase: Some(MutationPhase::Dom),
            dom_ops: self.random_dom_ops(rng, stats, budget),
            mutate_actions: false,
            refresh_document: false,
        }
    }

    fn random_dom_ops<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> Vec<DomMutationOp> {
        let count = rng.gen_range(1..=self.max_dom_ops_per_iteration);
        (0..count)
            .map(|_| DomMutationOp::random_with_budget(rng, stats, budget))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    use super::*;

    #[test]
    fn dom_phase_plan_mutates_only_dom() {
        let scheduler = MutationScheduler::new();
        let mut rng = StdRng::seed_from_u64(1);

        let plan = scheduler.choose(
            &mut rng,
            MutationPhase::Dom,
            true,
            None,
            DomMutationBudget::initial(),
        );

        assert_eq!(plan.phase, Some(MutationPhase::Dom));
        assert!(!plan.dom_ops.is_empty());
        assert!(!plan.mutate_actions);
    }

    #[test]
    fn user_interaction_phase_plan_mutates_only_actions() {
        let scheduler = MutationScheduler::new();
        let mut rng = StdRng::seed_from_u64(1);

        let plan = scheduler.choose(
            &mut rng,
            MutationPhase::UserInteraction,
            true,
            None,
            DomMutationBudget::initial(),
        );

        assert_eq!(plan.phase, Some(MutationPhase::UserInteraction));
        assert!(plan.dom_ops.is_empty());
        assert!(plan.mutate_actions);
    }

    #[test]
    fn budget_blocks_growth_ops() {
        let scheduler = MutationScheduler::new();
        let mut rng = StdRng::seed_from_u64(1);
        let stats = DocumentStats {
            element_count: 5,
            handler_count: 2,
            handler_statement_count: 10,
            css_rule_count: 0,
            keyframe_count: 0,
        };

        let plan = scheduler.choose(
            &mut rng,
            MutationPhase::Dom,
            true,
            Some(stats),
            DomMutationBudget::initial(),
        );

        assert!(!plan.dom_ops.contains(&DomMutationOp::InsertElement));
        assert!(!plan.dom_ops.contains(&DomMutationOp::AppendCssRule));
        assert!(!plan.dom_ops.contains(&DomMutationOp::AppendApi));
        assert!(!plan.dom_ops.contains(&DomMutationOp::InsertApi));
    }
}
