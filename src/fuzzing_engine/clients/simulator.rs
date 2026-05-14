use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::fuzzing_engine::actions::Action;
use crate::fuzzing_engine::config::AppConfig;
use crate::fuzzing_engine::metrics::IterationTimings;
use crate::fuzzing_engine::{EngineResult, engine_error};

#[derive(Debug, Clone)]
pub struct SimulatorConfig {
    pub simulator_dir: PathBuf,
    pub uv_cache_dir: PathBuf,
    pub browser_path: String,
    pub browser_kind: String,
    pub sancov_dir: PathBuf,
    pub asan_dir: PathBuf,
    pub out_dir: PathBuf,
    pub iteration_timeout_ms: u64,
    pub action_timeout_ms: u64,
    pub page_ready_timeout_ms: u64,
    pub post_actions_settle_ms: u64,
    pub inter_action_delay_ms: u64,
    pub disable_breakpad: bool,
    pub asan_symbolizer_path: Option<String>,
}

impl SimulatorConfig {
    pub fn from_app_config(config: &AppConfig) -> Self {
        Self {
            simulator_dir: config.simulator_dir.clone(),
            uv_cache_dir: config.uv_cache_dir.clone(),
            browser_path: config.browser_path.clone(),
            browser_kind: config.browser_kind.clone(),
            sancov_dir: config.sancov_dir.clone(),
            asan_dir: config.asan_dir.clone(),
            out_dir: config.out_dir.clone(),
            iteration_timeout_ms: config.iteration_timeout_ms,
            action_timeout_ms: config.action_timeout_ms,
            page_ready_timeout_ms: config.page_ready_timeout_ms,
            post_actions_settle_ms: config.post_actions_settle_ms,
            inter_action_delay_ms: config.inter_action_delay_ms,
            disable_breakpad: config.disable_breakpad,
            asan_symbolizer_path: config.asan_symbolizer_path.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct RunTestcaseRequest {
    pub iteration: u64,
    pub seed_id: String,
    pub html_path: Option<String>,
    pub initial_url: Option<String>,
    pub actions: Vec<Action>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimulatorResponse {
    pub status: String,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub actions_attempted: u64,
    #[serde(default)]
    pub actions_succeeded: u64,
    #[serde(default)]
    pub selector_fallbacks: u64,
    #[serde(default)]
    pub slow_actions: u64,
    #[serde(default)]
    pub timings: IterationTimings,
    #[serde(default)]
    pub action_trace: Vec<ActionTraceEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionTraceEntry {
    pub index: usize,
    pub kind: Option<String>,
    #[serde(default)]
    pub target: Option<ActionTargetTrace>,
    #[serde(default)]
    pub ok: bool,
    #[serde(default)]
    pub fallback_used: bool,
    #[serde(default)]
    pub elapsed_ms: u64,
    #[serde(default)]
    pub exists_before: Option<bool>,
    #[serde(default)]
    pub exists_after: Option<bool>,
    #[serde(default)]
    pub url_before: String,
    #[serde(default)]
    pub url_after: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "space", rename_all = "snake_case")]
pub enum ActionTargetTrace {
    Dom {
        selector: String,
        #[serde(default)]
        resolution: Option<String>,
        #[serde(default)]
        fallback: Option<bool>,
    },
    BrowserUi {
        role: String,
        name: String,
    },
}

pub struct SimulatorClient {
    child: Child,
    stdin: ChildStdin,
    reader: BufReader<ChildStdout>,
}

impl SimulatorClient {
    pub fn spawn(config: &SimulatorConfig) -> EngineResult<Self> {
        let mut child = Command::new("uv")
            .arg("run")
            .arg("--directory")
            .arg(&config.simulator_dir)
            .arg("python")
            .arg("-m")
            .arg("user_interaction_simulator")
            .arg("serve")
            .env("UV_CACHE_DIR", &config.uv_cache_dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| engine_error(format!("failed to spawn simulator: {error}")))?;

        ensure_child_running(&mut child, "user-interaction-simulator")?;
        let mut client = child_to_client(child)?;
        client.initialize(config)?;
        Ok(client)
    }

    pub fn run_testcase(&mut self, request: RunTestcaseRequest) -> EngineResult<SimulatorResponse> {
        self.send(&serde_json::json!({
            "cmd": "run_testcase",
            "protocol_version": 1,
            "iteration": request.iteration,
            "seed_id": request.seed_id,
            "html_path": request.html_path,
            "initial_url": request.initial_url,
            "actions": request.actions,
        }))?;
        self.response("run_testcase")
    }

    pub fn shutdown(&mut self) -> EngineResult<()> {
        self.send(&serde_json::json!({ "cmd": "shutdown", "protocol_version": 1 }))?;
        let _ = self.recv()?;
        Ok(())
    }

    fn initialize(&mut self, config: &SimulatorConfig) -> EngineResult<()> {
        self.send(&serde_json::json!({
            "cmd": "initialize",
            "protocol_version": 1,
            "browser_path": config.browser_path,
            "browser_kind": config.browser_kind,
            "sancov_dir": config.sancov_dir.to_string_lossy(),
            "asan_dir": config.asan_dir.to_string_lossy(),
            "out_dir": config.out_dir.to_string_lossy(),
            "iteration_timeout_ms": config.iteration_timeout_ms,
            "action_timeout_ms": config.action_timeout_ms,
            "page_ready_timeout_ms": config.page_ready_timeout_ms,
            "post_actions_settle_ms": config.post_actions_settle_ms,
            "inter_action_delay_ms": config.inter_action_delay_ms,
            "disable_breakpad": config.disable_breakpad,
            "asan_symbolizer_path": config.asan_symbolizer_path,
        }))?;
        let response: SimulatorResponse = self.response("initialize")?;
        if response.status != "ok" {
            return Err(engine_error(format!(
                "simulator initialize failed: {:?}",
                response.reason
            )));
        }
        Ok(())
    }

    fn response<T>(&mut self, label: &str) -> EngineResult<T>
    where
        T: for<'de> Deserialize<'de>,
    {
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
            return Err(engine_error("simulator exited unexpectedly"));
        }
        serde_json::from_str(line.trim()).map_err(|error| {
            engine_error(format!(
                "simulator returned invalid JSON: {error}; raw={line:?}"
            ))
        })
    }
}

impl Drop for SimulatorClient {
    fn drop(&mut self) {
        let _ = self.shutdown();
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

fn child_to_client(mut child: Child) -> EngineResult<SimulatorClient> {
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| engine_error("simulator stdin was not piped"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| engine_error("simulator stdout was not piped"))?;

    Ok(SimulatorClient {
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

pub fn optional_path_string(path: Option<&Path>) -> Option<String> {
    path.map(|path| path.to_string_lossy().to_string())
}
