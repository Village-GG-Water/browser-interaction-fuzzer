use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::time::{Duration, Instant};

use serde::Deserialize;

use crate::fuzzing_engine::actions::Action;
use crate::fuzzing_engine::input::DocumentStats;
use crate::fuzzing_engine::mutation::DomGenerationBudget;
use crate::fuzzing_engine::mutation::{DomMutationOp, InteractableMetadata, protocol_op_names};
use crate::fuzzing_engine::{EngineResult, engine_error};

#[derive(Debug, Clone)]
pub struct DomGeneratorConfig {
    pub generator_dir: PathBuf,
    pub uv_cache_dir: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GeneratedDocument {
    pub id: Option<String>,
    pub html: String,
    #[serde(default)]
    pub interactables: Vec<InteractableMetadata>,
    #[serde(default)]
    pub action_hints: Vec<Action>,
    #[serde(default)]
    pub stats: DocumentStats,
}

pub struct DomGeneratorClient {
    child: Child,
    stdin: ChildStdin,
    reader: BufReader<ChildStdout>,
}

impl DomGeneratorClient {
    pub fn spawn(config: &DomGeneratorConfig) -> EngineResult<Self> {
        let mut child = Command::new("uv")
            .arg("run")
            .arg("--directory")
            .arg(&config.generator_dir)
            .arg("python")
            .arg("main.py")
            .arg("serve")
            .env("UV_CACHE_DIR", &config.uv_cache_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| engine_error(format!("failed to spawn dom-generator: {error}")))?;

        ensure_child_running(&mut child, "dom-generator")?;
        child_to_client(child)
    }

    pub fn generate_document(
        &mut self,
        output_fdir: Option<&Path>,
        budget: Option<DomGenerationBudget>,
    ) -> EngineResult<GeneratedDocument> {
        self.send(&serde_json::json!({
            "cmd": "generate_document",
            "output_fdir": output_fdir.map(|path| path.to_string_lossy().to_string()),
            "budget": budget,
        }))?;
        self.document_response("generate_document")
    }

    pub fn load_document(&mut self, document_path: &Path) -> EngineResult<GeneratedDocument> {
        self.send(&serde_json::json!({
            "cmd": "load_document",
            "path": document_path.to_string_lossy(),
        }))?;
        self.document_response("load_document")
    }

    pub fn mutate_document(
        &mut self,
        source_path: &Path,
        output_path: &Path,
        ops: &[DomMutationOp],
    ) -> EngineResult<GeneratedDocument> {
        self.send(&serde_json::json!({
            "cmd": "mutate_document",
            "source_path": source_path.to_string_lossy(),
            "output_path": output_path.to_string_lossy(),
            "ops": protocol_op_names(ops),
        }))?;
        self.document_response("mutate_document")
    }

    pub fn shutdown(&mut self) -> EngineResult<()> {
        self.send(&serde_json::json!({ "cmd": "shutdown" }))?;
        let _ = self.recv()?;
        Ok(())
    }

    fn document_response(&mut self, label: &str) -> EngineResult<GeneratedDocument> {
        let response = self.recv()?;
        if let Some(error) = response.get("error").and_then(|value| value.as_str()) {
            return Err(engine_error(format!("{label} failed: {error}")));
        }
        serde_json::from_value(response)
            .map_err(|error| engine_error(format!("{label} returned malformed response: {error}")))
    }

    fn send(&mut self, message: &serde_json::Value) -> EngineResult<()> {
        let line = serde_json::to_string(message)?;
        writeln!(self.stdin, "{line}")?;
        self.stdin.flush()?;
        Ok(())
    }

    fn recv(&mut self) -> EngineResult<serde_json::Value> {
        let mut line = String::new();
        let bytes = self.reader.read_line(&mut line)?;
        if bytes == 0 {
            return Err(engine_error("dom-generator exited unexpectedly"));
        }
        serde_json::from_str(line.trim()).map_err(|error| {
            engine_error(format!(
                "dom-generator returned invalid JSON: {error}; raw={line:?}"
            ))
        })
    }
}

impl Drop for DomGeneratorClient {
    fn drop(&mut self) {
        let _ = self.send(&serde_json::json!({ "cmd": "shutdown" }));
        wait_then_kill(&mut self.child);
    }
}

fn ensure_child_running(child: &mut Child, label: &str) -> EngineResult<()> {
    std::thread::sleep(Duration::from_millis(100));
    match child.try_wait()? {
        Some(status) => Err(engine_error(format!(
            "{label} exited during startup: {status}"
        ))),
        None => Ok(()),
    }
}

fn child_to_client(mut child: Child) -> EngineResult<DomGeneratorClient> {
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| engine_error("dom-generator stdin was not piped"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| engine_error("dom-generator stdout was not piped"))?;

    Ok(DomGeneratorClient {
        child,
        stdin,
        reader: BufReader::new(stdout),
    })
}

fn wait_then_kill(child: &mut Child) {
    let deadline = Instant::now() + Duration::from_millis(1500);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => std::thread::sleep(Duration::from_millis(25)),
            Err(_) => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}
