use std::collections::VecDeque;

use rand::Rng;
use serde::{Deserialize, Serialize};

pub const REWARD_WINDOW: usize = 50;
const DOM_ELEMENT_STEP: usize = 5;
const DOM_HANDLER_STEP: usize = 1;
const DOM_CSS_STEP: usize = 2;
const ACTION_STEP: usize = 3;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MutationPhase {
    Dom,
    UserInteraction,
}

impl MutationPhase {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Dom => "dom",
            Self::UserInteraction => "user_interaction",
        }
    }

    pub fn from_str(value: &str) -> Option<Self> {
        match value {
            "dom" => Some(Self::Dom),
            "user_interaction" => Some(Self::UserInteraction),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DomGenerationBudget {
    pub min_elements: usize,
    pub max_elements: usize,
    pub max_depth: usize,
    pub max_attributes: usize,
    pub max_handlers: usize,
    pub min_handler_statements: usize,
    pub max_handler_statements: usize,
    pub max_css_rules: usize,
    pub max_keyframes: usize,
    pub max_css_variables: usize,
}

impl DomGenerationBudget {
    pub fn initial() -> Self {
        Self {
            min_elements: 3,
            max_elements: 5,
            max_depth: 2,
            max_attributes: 2,
            max_handlers: 2,
            min_handler_statements: 3,
            max_handler_statements: 5,
            max_css_rules: 0,
            max_keyframes: 0,
            max_css_variables: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DomMutationBudget {
    pub max_elements: usize,
    pub max_handlers: usize,
    pub max_css_rules: usize,
}

impl DomMutationBudget {
    pub fn initial() -> Self {
        Self {
            max_elements: 5,
            max_handlers: 2,
            max_css_rules: 0,
        }
    }

    fn grow(&mut self) {
        self.max_elements = (self.max_elements + DOM_ELEMENT_STEP).min(80);
        self.max_handlers = (self.max_handlers + DOM_HANDLER_STEP).min(8);
        self.max_css_rules = if self.max_css_rules == 0 {
            DOM_CSS_STEP
        } else {
            (self.max_css_rules + DOM_CSS_STEP).min(20)
        };
    }

    pub fn max_handler_statements(self) -> usize {
        self.max_handlers * DomGenerationBudget::initial().max_handler_statements
    }
}

#[derive(Debug, Clone, Default)]
pub struct PhaseStats {
    rewards: VecDeque<bool>,
}

impl PhaseStats {
    fn record(&mut self, success: bool) {
        self.rewards.push_back(success);
        if self.rewards.len() > REWARD_WINDOW {
            self.rewards.pop_front();
        }
    }

    pub fn successes(&self) -> usize {
        self.rewards.iter().filter(|&&success| success).count()
    }

    pub fn failures(&self) -> usize {
        self.rewards.len() - self.successes()
    }
}

#[derive(Debug, Clone, Default)]
pub struct PhaseSelector {
    dom: PhaseStats,
    user_interaction: PhaseStats,
}

impl PhaseSelector {
    pub fn choose<R: Rng + ?Sized>(&self, rng: &mut R, document_available: bool) -> MutationPhase {
        if !document_available {
            return MutationPhase::UserInteraction;
        }

        let dom_sample = beta_sample(
            rng,
            1.0 + self.dom.successes() as f64,
            1.0 + self.dom.failures() as f64,
        );
        let user_sample = beta_sample(
            rng,
            1.0 + self.user_interaction.successes() as f64,
            1.0 + self.user_interaction.failures() as f64,
        );
        if dom_sample >= user_sample {
            MutationPhase::Dom
        } else {
            MutationPhase::UserInteraction
        }
    }

    pub fn record(&mut self, phase: MutationPhase, success: bool) {
        match phase {
            MutationPhase::Dom => self.dom.record(success),
            MutationPhase::UserInteraction => self.user_interaction.record(success),
        }
    }

    pub fn snapshot(&self) -> PhaseSelectorSnapshot {
        PhaseSelectorSnapshot {
            dom_successes: self.dom.successes(),
            dom_failures: self.dom.failures(),
            user_successes: self.user_interaction.successes(),
            user_failures: self.user_interaction.failures(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct PhaseSelectorSnapshot {
    pub dom_successes: usize,
    pub dom_failures: usize,
    pub user_successes: usize,
    pub user_failures: usize,
}

#[derive(Debug, Clone, Copy)]
pub struct MutationPolicySnapshot {
    pub dom_budget: DomMutationBudget,
    pub action_budget: usize,
    pub stagnation_runs: usize,
    pub phase_stats: PhaseSelectorSnapshot,
}

#[derive(Debug)]
pub struct MutationPolicyState {
    phase_selector: PhaseSelector,
    dom_budget: DomMutationBudget,
    action_budget: usize,
    max_actions: usize,
    stagnation_runs: usize,
}

impl MutationPolicyState {
    pub fn new(max_actions: usize) -> Self {
        Self {
            phase_selector: PhaseSelector::default(),
            dom_budget: DomMutationBudget::initial(),
            action_budget: ACTION_STEP.min(max_actions.max(1)),
            max_actions: max_actions.max(1),
            stagnation_runs: 0,
        }
    }

    pub fn choose_phase<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        document_available: bool,
    ) -> MutationPhase {
        self.phase_selector.choose(rng, document_available)
    }

    pub fn record_result(&mut self, phase: Option<MutationPhase>, new_coverage: bool) {
        if let Some(phase) = phase {
            self.phase_selector.record(phase, new_coverage);
        }

        if new_coverage {
            self.stagnation_runs = 0;
            return;
        }

        self.stagnation_runs += 1;
        if self.stagnation_runs >= REWARD_WINDOW {
            self.dom_budget.grow();
            self.action_budget = (self.action_budget + ACTION_STEP).min(self.max_actions);
            self.stagnation_runs = 0;
        }
    }

    pub fn dom_budget(&self) -> DomMutationBudget {
        self.dom_budget
    }

    pub fn action_budget(&self) -> usize {
        self.action_budget
    }

    pub fn initial_generation_budget(&self) -> DomGenerationBudget {
        DomGenerationBudget::initial()
    }

    pub fn snapshot(&self) -> MutationPolicySnapshot {
        MutationPolicySnapshot {
            dom_budget: self.dom_budget,
            action_budget: self.action_budget,
            stagnation_runs: self.stagnation_runs,
            phase_stats: self.phase_selector.snapshot(),
        }
    }
}

fn beta_sample<R: Rng + ?Sized>(rng: &mut R, alpha: f64, beta: f64) -> f64 {
    let x = gamma_sample(rng, alpha);
    let y = gamma_sample(rng, beta);
    if x + y == 0.0 { 0.5 } else { x / (x + y) }
}

fn gamma_sample<R: Rng + ?Sized>(rng: &mut R, shape: f64) -> f64 {
    debug_assert!(shape >= 1.0);
    let d = shape - 1.0 / 3.0;
    let c = (1.0 / (9.0 * d)).sqrt();
    loop {
        let x = standard_normal(rng);
        let v = 1.0 + c * x;
        if v <= 0.0 {
            continue;
        }
        let v3 = v * v * v;
        let u = rng.gen_range(0.0..1.0);
        if u < 1.0 - 0.0331 * x.powi(4) {
            return d * v3;
        }
        if u.ln() < 0.5 * x * x + d * (1.0 - v3 + v3.ln()) {
            return d * v3;
        }
    }
}

fn standard_normal<R: Rng + ?Sized>(rng: &mut R) -> f64 {
    let u1 = rng.gen_range(0.0..1.0_f64).clamp(f64::MIN_POSITIVE, 1.0);
    let u2 = rng.gen_range(0.0..1.0);
    (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
}

#[cfg(test)]
mod tests {
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    use super::*;

    #[test]
    fn policy_grows_budgets_after_stagnation_window() {
        let mut policy = MutationPolicyState::new(12);

        for _ in 0..REWARD_WINDOW {
            policy.record_result(Some(MutationPhase::Dom), false);
        }

        let snapshot = policy.snapshot();
        assert_eq!(snapshot.dom_budget.max_elements, 10);
        assert_eq!(snapshot.dom_budget.max_handlers, 3);
        assert_eq!(snapshot.dom_budget.max_css_rules, 2);
        assert_eq!(snapshot.action_budget, 6);
        assert_eq!(snapshot.stagnation_runs, 0);
    }

    #[test]
    fn coverage_success_resets_stagnation_without_shrinking_budget() {
        let mut policy = MutationPolicyState::new(12);
        for _ in 0..REWARD_WINDOW {
            policy.record_result(Some(MutationPhase::Dom), false);
        }

        policy.record_result(Some(MutationPhase::UserInteraction), true);

        let snapshot = policy.snapshot();
        assert_eq!(snapshot.dom_budget.max_elements, 10);
        assert_eq!(snapshot.action_budget, 6);
        assert_eq!(snapshot.stagnation_runs, 0);
        assert_eq!(snapshot.phase_stats.user_successes, 1);
    }

    #[test]
    fn no_document_forces_user_interaction_phase() {
        let policy = MutationPolicyState::new(12);
        let mut rng = StdRng::seed_from_u64(7);

        assert_eq!(
            policy.choose_phase(&mut rng, false),
            MutationPhase::UserInteraction
        );
    }

    #[test]
    fn beta_selector_records_phase_windows() {
        let mut selector = PhaseSelector::default();
        selector.record(MutationPhase::Dom, true);
        selector.record(MutationPhase::Dom, false);
        selector.record(MutationPhase::UserInteraction, false);

        let snapshot = selector.snapshot();
        assert_eq!(snapshot.dom_successes, 1);
        assert_eq!(snapshot.dom_failures, 1);
        assert_eq!(snapshot.user_successes, 0);
        assert_eq!(snapshot.user_failures, 1);
    }
}
