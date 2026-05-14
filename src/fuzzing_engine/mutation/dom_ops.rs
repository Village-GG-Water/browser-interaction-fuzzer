use rand::Rng;
use serde::{Deserialize, Serialize};

use crate::fuzzing_engine::input::DocumentStats;

use super::policy::DomMutationBudget;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DomMutationOp {
    InsertElement,
    AppendAttribute,
    MutateAttribute,
    ReplaceAttribute,
    MutateText,
    AppendCssRule,
    ReplaceCssRule,
    MutateCssRule,
    MutateCssKeyframes,
    AppendApi,
    InsertApi,
    ReplaceApi,
    MutateApi,
    ReorderStatement,
    RemoveStatement,
    InsertStatement,
    MutateApiArgs,
    InsertSelfInvalidateHandler,
    InsertCrossInvalidateHandler,
    WrapInvalidationAsync,
    InsertFocusInvalidateHandler,
}

impl DomMutationOp {
    pub fn as_protocol_name(self) -> &'static str {
        match self {
            Self::InsertElement => "insert_element",
            Self::AppendAttribute => "append_attribute",
            Self::MutateAttribute => "mutate_attribute",
            Self::ReplaceAttribute => "replace_attribute",
            Self::MutateText => "mutate_text",
            Self::AppendCssRule => "append_css_rule",
            Self::ReplaceCssRule => "replace_css_rule",
            Self::MutateCssRule => "mutate_css_rule",
            Self::MutateCssKeyframes => "mutate_css_keyframes",
            Self::AppendApi => "append_api",
            Self::InsertApi => "insert_api",
            Self::ReplaceApi => "replace_api",
            Self::MutateApi => "mutate_api",
            Self::ReorderStatement => "reorder_statement",
            Self::RemoveStatement => "remove_statement",
            Self::InsertStatement => "insert_statement",
            Self::MutateApiArgs => "mutate_api_args",
            Self::InsertSelfInvalidateHandler => "insert_self_invalidate_handler",
            Self::InsertCrossInvalidateHandler => "insert_cross_invalidate_handler",
            Self::WrapInvalidationAsync => "wrap_invalidation_async",
            Self::InsertFocusInvalidateHandler => "insert_focus_invalidate_handler",
        }
    }

    pub fn random_with_budget<R: Rng + ?Sized>(
        rng: &mut R,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> Self {
        let mut weighted = Vec::new();
        for op in [
            Self::InsertElement,
            Self::AppendAttribute,
            Self::MutateAttribute,
            Self::ReplaceAttribute,
            Self::MutateText,
            Self::AppendCssRule,
            Self::ReplaceCssRule,
            Self::MutateCssRule,
            Self::MutateCssKeyframes,
            Self::AppendApi,
            Self::InsertApi,
            Self::ReplaceApi,
            Self::MutateApi,
            Self::ReorderStatement,
            Self::RemoveStatement,
            Self::InsertStatement,
            Self::MutateApiArgs,
            Self::MutateApiArgs,
            Self::MutateApiArgs,
            Self::InsertSelfInvalidateHandler,
            Self::InsertSelfInvalidateHandler,
            Self::InsertCrossInvalidateHandler,
            Self::InsertCrossInvalidateHandler,
            Self::WrapInvalidationAsync,
            Self::InsertFocusInvalidateHandler,
        ] {
            if op.allowed_by_budget(stats, budget) {
                weighted.push(op);
            }
        }
        if weighted.is_empty() {
            return Self::MutateApiArgs;
        }
        weighted[rng.gen_range(0..weighted.len())]
    }

    pub fn allowed_by_budget(
        self,
        stats: Option<DocumentStats>,
        budget: DomMutationBudget,
    ) -> bool {
        let Some(stats) = stats else {
            return !matches!(self, Self::AppendCssRule | Self::MutateCssKeyframes);
        };

        match self {
            Self::InsertElement => stats.element_count < budget.max_elements,
            Self::AppendCssRule => {
                budget.max_css_rules > 0 && stats.css_rule_count < budget.max_css_rules
            }
            Self::MutateCssKeyframes => budget.max_css_rules >= 6,
            Self::AppendApi | Self::InsertApi | Self::InsertStatement => {
                stats.handler_statement_count < budget.max_handler_statements()
            }
            _ => true,
        }
    }

    pub fn is_lifecycle_setup(self) -> bool {
        matches!(
            self,
            Self::InsertSelfInvalidateHandler
                | Self::InsertCrossInvalidateHandler
                | Self::WrapInvalidationAsync
                | Self::InsertFocusInvalidateHandler
        )
    }
}

pub fn protocol_op_names(ops: &[DomMutationOp]) -> Vec<&'static str> {
    ops.iter().map(|op| op.as_protocol_name()).collect()
}
