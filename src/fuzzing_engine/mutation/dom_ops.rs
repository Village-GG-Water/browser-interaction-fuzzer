use rand::Rng;
use serde::{Deserialize, Serialize};

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
        }
    }

    pub fn random<R: Rng + ?Sized>(rng: &mut R) -> Self {
        let weighted = [
            Self::InsertElement,
            Self::AppendAttribute,
            Self::MutateAttribute,
            Self::ReplaceAttribute,
            Self::MutateText,
            Self::AppendCssRule,
            Self::MutateCssRule,
            Self::AppendApi,
            Self::InsertApi,
            Self::ReplaceApi,
            Self::MutateApi,
            Self::ReorderStatement,
            Self::InsertStatement,
            Self::MutateApiArgs,
            Self::MutateApiArgs,
            Self::MutateApiArgs,
        ];
        weighted[rng.gen_range(0..weighted.len())]
    }
}

pub fn protocol_op_names(ops: &[DomMutationOp]) -> Vec<&'static str> {
    ops.iter().map(|op| op.as_protocol_name()).collect()
}
