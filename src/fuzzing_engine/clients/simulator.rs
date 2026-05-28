use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
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
    pub simulator_response_timeout_ms: u64,
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
            simulator_response_timeout_ms: config.simulator_response_timeout_ms,
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
    config: SimulatorConfig,
    process: SimulatorProcess,
}

struct SimulatorProcess {
    child: Child,
    stdin: ChildStdin,
    receiver: Receiver<EngineResult<String>>,
}

impl SimulatorClient {
    pub fn spawn(config: &SimulatorConfig) -> EngineResult<Self> {
        let mut client = Self {
            config: config.clone(),
            process: spawn_process(config)?,
        };
        client.initialize()?;
        Ok(client)
    }

    pub fn run_testcase(&mut self, request: RunTestcaseRequest) -> EngineResult<SimulatorResponse> {
        let message = serde_json::json!({
            "cmd": "run_testcase",
            "protocol_version": 1,
            "iteration": request.iteration,
            "seed_id": request.seed_id,
            "html_path": request.html_path,
            "initial_url": request.initial_url,
            "actions": request.actions,
        });
        if let Err(error) = self.send(&message) {
            return self.restart_and_fail("run_testcase", format!("send failed: {error}"));
        }

        let timeout = self.response_timeout();
        match self.response_with_timeout("run_testcase", timeout) {
            Ok(response) => Ok(response),
            Err(error) => self.restart_and_fail("run_testcase", error.to_string()),
        }
    }

    fn shutdown(&mut self, timeout: Duration) -> EngineResult<()> {
        self.send(&serde_json::json!({ "cmd": "shutdown", "protocol_version": 1 }))?;
        let _ = self.recv_with_timeout("shutdown", timeout)?;
        Ok(())
    }

    fn initialize(&mut self) -> EngineResult<()> {
        self.send(&serde_json::json!({
            "cmd": "initialize",
            "protocol_version": 1,
            "browser_path": &self.config.browser_path,
            "browser_kind": &self.config.browser_kind,
            "sancov_dir": self.config.sancov_dir.to_string_lossy(),
            "asan_dir": self.config.asan_dir.to_string_lossy(),
            "out_dir": self.config.out_dir.to_string_lossy(),
            "iteration_timeout_ms": self.config.iteration_timeout_ms,
            "action_timeout_ms": self.config.action_timeout_ms,
            "page_ready_timeout_ms": self.config.page_ready_timeout_ms,
            "post_actions_settle_ms": self.config.post_actions_settle_ms,
            "inter_action_delay_ms": self.config.inter_action_delay_ms,
            "disable_breakpad": self.config.disable_breakpad,
            "asan_symbolizer_path": &self.config.asan_symbolizer_path,
        }))?;
        let response: SimulatorResponse =
            self.response_with_timeout("initialize", self.response_timeout())?;
        if response.status != "ok" {
            return Err(engine_error(format!(
                "simulator initialize failed: {:?}",
                response.reason
            )));
        }
        Ok(())
    }

    fn response_with_timeout<T>(&mut self, label: &str, timeout: Duration) -> EngineResult<T>
    where
        T: for<'de> Deserialize<'de>,
    {
        let response = self.recv_with_timeout(label, timeout)?;
        if let Some(error) = response.get("error").and_then(|value| value.as_str()) {
            return Err(engine_error(format!("{label} failed: {error}")));
        }
        serde_json::from_value(response)
            .map_err(|error| engine_error(format!("{label} returned malformed response: {error}")))
    }

    fn send(&mut self, message: &serde_json::Value) -> EngineResult<()> {
        let line = serde_json::to_string(message)?;
        writeln!(self.process.stdin, "{line}")?;
        self.process.stdin.flush()?;
        Ok(())
    }

    fn recv_with_timeout(
        &mut self,
        label: &str,
        timeout: Duration,
    ) -> EngineResult<serde_json::Value> {
        let line = match self.process.receiver.recv_timeout(timeout) {
            Ok(Ok(line)) => line,
            Ok(Err(error)) => return Err(error),
            Err(RecvTimeoutError::Timeout) => {
                return Err(engine_error(format!(
                    "{label} response timed out after {}ms",
                    timeout.as_millis()
                )));
            }
            Err(RecvTimeoutError::Disconnected) => {
                return Err(engine_error("simulator exited unexpectedly"));
            }
        };
        serde_json::from_str(line.trim()).map_err(|error| {
            engine_error(format!(
                "simulator returned invalid JSON: {error}; raw={line:?}"
            ))
        })
    }

    fn restart_and_fail<T>(&mut self, label: &str, reason: String) -> EngineResult<T> {
        let detail = reason_without_label(label, &reason);
        match self.restart_after_failure(label, &reason) {
            Ok(()) => Err(engine_error(format!(
                "{label} failed: {detail}; simulator restarted"
            ))),
            Err(restart_error) => Err(engine_error(format!(
                "{label} failed: {detail}; failed to restart simulator: {restart_error}"
            ))),
        }
    }

    fn restart_after_failure(&mut self, label: &str, reason: &str) -> EngineResult<()> {
        let detail = reason_without_label(label, reason);
        eprintln!("[simulator] {label} {detail}; restarting simulator");
        terminate_process_tree(&mut self.process.child);
        self.process = spawn_process(&self.config)?;
        if let Err(error) = self.initialize() {
            terminate_process_tree(&mut self.process.child);
            return Err(error);
        }
        eprintln!("[simulator] restarted after {label} failure");
        Ok(())
    }

    fn response_timeout(&self) -> Duration {
        Duration::from_millis(self.config.simulator_response_timeout_ms)
    }
}

fn reason_without_label<'a>(label: &str, reason: &'a str) -> &'a str {
    reason
        .strip_prefix(label)
        .map(str::trim_start)
        .unwrap_or(reason)
}

impl Drop for SimulatorClient {
    fn drop(&mut self) {
        let _ = self.shutdown(Duration::from_millis(500));
        terminate_process_tree(&mut self.process.child);
    }
}

fn spawn_process(config: &SimulatorConfig) -> EngineResult<SimulatorProcess> {
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
    child_to_process(child)
}

fn ensure_child_running(child: &mut Child, label: &str) -> EngineResult<()> {
    thread::sleep(Duration::from_millis(100));
    match child.try_wait()? {
        Some(status) => Err(engine_error(format!(
            "{label} exited during startup: {status}"
        ))),
        None => Ok(()),
    }
}

fn child_to_process(mut child: Child) -> EngineResult<SimulatorProcess> {
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| engine_error("simulator stdin was not piped"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| engine_error("simulator stdout was not piped"))?;

    Ok(SimulatorProcess {
        child,
        stdin,
        receiver: spawn_reader_thread(stdout),
    })
}

fn spawn_reader_thread(stdout: ChildStdout) -> Receiver<EngineResult<String>> {
    let (sender, receiver) = mpsc::channel();
    let _ = thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let message = match line {
                Ok(line) => Ok(line),
                Err(error) => Err(engine_error(format!(
                    "simulator stdout read failed: {error}"
                ))),
            };
            let should_stop = message.is_err();
            if sender.send(message).is_err() || should_stop {
                return;
            }
        }
    });
    receiver
}

fn terminate_process_tree(child: &mut Child) {
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }
    kill_process_tree(child);
    wait_then_kill(child);
}

#[cfg(windows)]
fn kill_process_tree(child: &mut Child) {
    let pid = child.id().to_string();
    let _ = Command::new("taskkill")
        .args(["/PID", &pid, "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(not(windows))]
fn kill_process_tree(child: &mut Child) {
    let _ = child.kill();
}

fn wait_then_kill(child: &mut Child) {
    let deadline = Instant::now() + Duration::from_millis(1500);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => thread::sleep(Duration::from_millis(25)),
            Err(_) => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

pub fn optional_path_string(path: Option<&Path>) -> Option<String> {
    path.map(|path| path.to_string_lossy().to_string())
}
