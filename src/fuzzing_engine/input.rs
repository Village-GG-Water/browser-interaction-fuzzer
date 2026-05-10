use std::path::{Path, PathBuf};

use libafl::inputs::Input;
use serde::{Deserialize, Serialize};

use super::actions::Action;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InteractionScope {
    Dom,
    BrowserUi,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DocumentSpec {
    Fdir {
        path: PathBuf,
    },
    #[serde(rename = "none")]
    NoDocument {
        initial_url: String,
    },
}

impl DocumentSpec {
    pub fn relative_path(&self) -> Option<&Path> {
        match self {
            Self::Fdir { path } => Some(path.as_path()),
            Self::NoDocument { .. } => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestcaseSpec {
    pub schema_version: u32,
    pub seed_id: String,
    pub document: DocumentSpec,
    pub interaction_scope: Vec<InteractionScope>,
    pub actions_path: PathBuf,
}

#[derive(Debug, Clone, Hash, Serialize, Deserialize)]
pub struct FuzzInput {
    pub seed_id: String,
    pub seed_dir: PathBuf,
    pub document: DocumentSpec,
    pub actions: Vec<Action>,
    pub snapshot_path: Option<PathBuf>,
}

impl Input for FuzzInput {}

impl FuzzInput {
    pub fn html_path(&self) -> Option<&Path> {
        self.snapshot_path.as_deref()
    }

    pub fn initial_url(&self) -> Option<&str> {
        match &self.document {
            DocumentSpec::NoDocument { initial_url } => Some(initial_url.as_str()),
            DocumentSpec::Fdir { .. } => None,
        }
    }
}
