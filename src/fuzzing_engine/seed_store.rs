use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use super::actions::{Action, validate_actions};
use super::input::{DocumentSpec, FuzzInput, TestcaseSpec};
use super::{EngineResult, engine_error};

#[derive(Debug, Clone, Deserialize)]
pub struct SeedMetadata {
    #[serde(default = "unknown_source_kind")]
    pub source_kind: String,
}

impl Default for SeedMetadata {
    fn default() -> Self {
        Self {
            source_kind: unknown_source_kind(),
        }
    }
}

fn unknown_source_kind() -> String {
    "unknown".to_string()
}

#[derive(Debug, Clone)]
pub struct SeedInput {
    pub spec: TestcaseSpec,
    pub metadata: SeedMetadata,
    pub input: FuzzInput,
}

#[derive(Debug, Clone)]
pub struct SeedStore {
    root: PathBuf,
}

impl SeedStore {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    pub fn load_all(&self) -> EngineResult<Vec<SeedInput>> {
        let mut seeds = Vec::new();
        if !self.root.exists() {
            return Ok(seeds);
        }

        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            if !entry.file_type()?.is_dir() {
                continue;
            }
            match self.load_seed(&entry.path()) {
                Ok(seed) => seeds.push(seed),
                Err(error) => eprintln!("[seed] skipping {}: {error}", entry.path().display()),
            }
        }

        seeds.sort_by(|left, right| left.spec.seed_id.cmp(&right.spec.seed_id));
        Ok(seeds)
    }

    pub fn load_seed(&self, seed_dir: &Path) -> EngineResult<SeedInput> {
        let spec: TestcaseSpec = read_json(&seed_dir.join("testcase.json"))?;
        let actions: Vec<Action> = read_json(&seed_dir.join(&spec.actions_path))?;
        validate_actions(&actions).map_err(engine_error)?;
        let metadata = read_json(&seed_dir.join("metadata.json")).unwrap_or_default();

        let snapshot_path = seed_dir
            .join("snapshot.html")
            .exists()
            .then(|| seed_dir.join("snapshot.html"));

        Ok(SeedInput {
            input: FuzzInput {
                seed_id: spec.seed_id.clone(),
                seed_dir: seed_dir.to_path_buf(),
                document: absolute_document(seed_dir, &spec.document),
                actions,
                snapshot_path,
                document_stats: None,
                mutation_phase: None,
            },
            spec,
            metadata,
        })
    }
}

pub fn read_json<T>(path: &Path) -> EngineResult<T>
where
    T: for<'de> Deserialize<'de>,
{
    let raw = fs::read_to_string(path)?;
    serde_json::from_str(&raw)
        .map_err(|error| engine_error(format!("failed to parse {}: {error}", path.display())))
}

fn absolute_document(seed_dir: &Path, document: &DocumentSpec) -> DocumentSpec {
    match document {
        DocumentSpec::Fdir { path } => DocumentSpec::Fdir {
            path: seed_dir.join(path),
        },
        DocumentSpec::NoDocument { initial_url } => DocumentSpec::NoDocument {
            initial_url: initial_url.clone(),
        },
    }
}
