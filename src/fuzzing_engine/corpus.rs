use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::actions::{Action, validate_actions};
use super::input::{DocumentSpec, FuzzInput, InteractionScope, TestcaseSpec};
use super::{EngineResult, engine_error};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeedMetadata {
    pub schema_version: u32,
    pub seed_id: String,
    pub created_at: String,
    pub source_kind: String,
    pub generator_version: String,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coverage_edges: Option<u64>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub crash_summary: Option<String>,
}

#[derive(Debug, Clone)]
pub struct CorpusSeed {
    pub spec: TestcaseSpec,
    pub metadata: SeedMetadata,
    pub input: FuzzInput,
}

#[derive(Debug, Clone)]
pub struct CorpusStore {
    root: PathBuf,
}

impl CorpusStore {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    pub fn load_all(&self) -> EngineResult<Vec<CorpusSeed>> {
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
                Err(error) => eprintln!("[corpus] skipping {}: {error}", entry.path().display()),
            }
        }

        seeds.sort_by(|left, right| left.spec.seed_id.cmp(&right.spec.seed_id));
        Ok(seeds)
    }

    pub fn load_seed(&self, seed_dir: &Path) -> EngineResult<CorpusSeed> {
        let spec: TestcaseSpec = read_json(&seed_dir.join("testcase.json"))?;
        let actions: Vec<Action> = read_json(&seed_dir.join(&spec.actions_path))?;
        validate_actions(&actions).map_err(engine_error)?;
        let metadata =
            read_json(&seed_dir.join("metadata.json")).unwrap_or_else(|_| SeedMetadata {
                schema_version: 1,
                seed_id: spec.seed_id.clone(),
                created_at: "unknown".to_string(),
                source_kind: "unknown".to_string(),
                generator_version: "unknown".to_string(),
                coverage_edges: None,
                crash_summary: None,
            });

        let snapshot_path = seed_dir
            .join("snapshot.html")
            .exists()
            .then(|| seed_dir.join("snapshot.html"));

        Ok(CorpusSeed {
            input: FuzzInput {
                seed_id: spec.seed_id.clone(),
                seed_dir: seed_dir.to_path_buf(),
                document: absolute_document(seed_dir, &spec.document),
                actions,
                snapshot_path,
            },
            spec,
            metadata,
        })
    }

    pub fn next_seed_id(&self, prefix: &str) -> EngineResult<String> {
        let mut next = 1_u64;
        if self.root.exists() {
            for entry in fs::read_dir(&self.root)? {
                let entry = entry?;
                let name = entry.file_name().to_string_lossy().to_string();
                if let Some(suffix) = name.strip_prefix(prefix)
                    && let Ok(value) = suffix.parse::<u64>()
                {
                    next = next.max(value + 1);
                }
            }
        }
        Ok(format!("{prefix}{next:06}"))
    }

    pub fn write_seed(
        &self,
        seed_id: &str,
        document: DocumentSpec,
        actions: &[Action],
        metadata: &SeedMetadata,
        snapshot_source: Option<&Path>,
        fdir_source: Option<&Path>,
    ) -> EngineResult<PathBuf> {
        let seed_dir = self.root.join(seed_id);
        fs::create_dir_all(&seed_dir)?;

        if let Some(source) = fdir_source {
            fs::copy(source, seed_dir.join("document.fdir"))?;
        }
        if let Some(source) = snapshot_source {
            fs::copy(source, seed_dir.join("snapshot.html"))?;
        }

        let relative_document = relative_document(&document);
        let spec = TestcaseSpec {
            schema_version: 1,
            seed_id: seed_id.to_string(),
            document: relative_document,
            interaction_scope: interaction_scope(&document),
            actions_path: PathBuf::from("actions.json"),
        };

        write_json(&seed_dir.join("testcase.json"), &spec)?;
        write_json(&seed_dir.join("actions.json"), actions)?;
        write_json(&seed_dir.join("metadata.json"), metadata)?;
        Ok(seed_dir)
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

pub fn write_json<T>(path: &Path, value: &T) -> EngineResult<()>
where
    T: Serialize + ?Sized,
{
    let raw = serde_json::to_string_pretty(value)?;
    fs::write(path, format!("{raw}\n"))?;
    Ok(())
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

fn relative_document(document: &DocumentSpec) -> DocumentSpec {
    match document {
        DocumentSpec::Fdir { .. } => DocumentSpec::Fdir {
            path: PathBuf::from("document.fdir"),
        },
        DocumentSpec::NoDocument { initial_url } => DocumentSpec::NoDocument {
            initial_url: initial_url.clone(),
        },
    }
}

fn interaction_scope(document: &DocumentSpec) -> Vec<InteractionScope> {
    match document {
        DocumentSpec::Fdir { .. } => vec![InteractionScope::Dom, InteractionScope::BrowserUi],
        DocumentSpec::NoDocument { .. } => vec![InteractionScope::BrowserUi],
    }
}
