use rand::Rng;

use super::dom_ops::DomMutationOp;

#[derive(Debug, Clone, Default)]
pub struct MutationPlan {
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

    pub fn choose<R: Rng + ?Sized>(&self, rng: &mut R, document_available: bool) -> MutationPlan {
        if !document_available {
            return MutationPlan {
                dom_ops: Vec::new(),
                mutate_actions: true,
                refresh_document: false,
            };
        }

        match rng.gen_range(0..100) {
            0..=14 => MutationPlan {
                refresh_document: true,
                mutate_actions: true,
                dom_ops: Vec::new(),
            },
            15..=44 => MutationPlan {
                dom_ops: self.random_dom_ops(rng),
                mutate_actions: false,
                refresh_document: false,
            },
            45..=84 => MutationPlan {
                dom_ops: self.random_dom_ops(rng),
                mutate_actions: true,
                refresh_document: false,
            },
            _ => MutationPlan {
                dom_ops: Vec::new(),
                mutate_actions: true,
                refresh_document: false,
            },
        }
    }

    fn random_dom_ops<R: Rng + ?Sized>(&self, rng: &mut R) -> Vec<DomMutationOp> {
        let count = rng.gen_range(1..=self.max_dom_ops_per_iteration);
        (0..count).map(|_| DomMutationOp::random(rng)).collect()
    }
}
