use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime};

use super::EngineResult;
use super::actions::Action;
use super::clients::{
    RunTestcaseRequest, SimulatorClient, SimulatorResponse, optional_path_string,
};
use super::coverage::{CoverageTracker, delete_sancov_files, parse_recent_sancov_dir};
use super::crash::{ClassifiedCrash, CrashType, find_and_classify_asan_report};
use super::input::FuzzInput;

#[derive(Debug)]
pub struct ExecutionOutcome {
    pub response: SimulatorResponse,
    pub new_coverage_edges: usize,
    pub classified_crash: Option<ClassifiedCrash>,
    pub timed_out: bool,
}

impl ExecutionOutcome {
    pub fn crash_type(&self) -> Option<CrashType> {
        if let Some(crash) = &self.classified_crash {
            Some(crash.crash_type)
        } else if self.timed_out {
            Some(CrashType::Timeout)
        } else if self.response.status == "crash" {
            Some(CrashType::Unknown)
        } else {
            None
        }
    }

    pub fn is_crash(&self) -> bool {
        self.crash_type().is_some()
    }
}

pub struct TestcaseExecutor {
    simulator: SimulatorClient,
    sancov_dir: PathBuf,
    asan_dir: PathBuf,
}

impl TestcaseExecutor {
    pub fn new(simulator: SimulatorClient, sancov_dir: PathBuf, asan_dir: PathBuf) -> Self {
        Self {
            simulator,
            sancov_dir,
            asan_dir,
        }
    }

    pub fn run(
        &mut self,
        iteration: u64,
        input: &FuzzInput,
        coverage: &mut CoverageTracker,
    ) -> EngineResult<ExecutionOutcome> {
        let iteration_started = Instant::now();
        let started_at = SystemTime::now();
        let response = self.simulator.run_testcase(RunTestcaseRequest {
            iteration,
            seed_id: input.seed_id.clone(),
            html_path: optional_path_string(input.html_path()),
            initial_url: input.initial_url().map(|value| value.to_string()),
            actions: input.actions.clone(),
        })?;

        let asan_started = Instant::now();
        let classified_crash = find_and_classify_asan_report(&self.asan_dir, started_at);
        let asan_scan_ms = elapsed_ms(asan_started);

        let sancov_started = Instant::now();
        let (pcs, parsed_files) = parse_recent_sancov_dir(&self.sancov_dir, started_at)?;
        let sancov_parse_ms = elapsed_ms(sancov_started);
        let new_coverage_edges = coverage.update(&pcs);
        delete_sancov_files(&parsed_files);

        let mut response = response;
        response.timings.asan_scan_ms = asan_scan_ms;
        response.timings.sancov_parse_ms = sancov_parse_ms;
        response.timings.iteration_total_ms = elapsed_ms(iteration_started);

        Ok(ExecutionOutcome {
            timed_out: response.status == "timeout",
            response,
            new_coverage_edges,
            classified_crash,
        })
    }
}

pub fn save_crash_artifacts(
    crash_dir: &Path,
    iteration: u64,
    input: &FuzzInput,
    actions: &[Action],
    response: &SimulatorResponse,
    classified_crash: Option<&ClassifiedCrash>,
) -> EngineResult<PathBuf> {
    let case_dir = crash_dir.join(format!("crash_{iteration:06}"));
    fs::create_dir_all(&case_dir)?;

    if let Some(snapshot) = input.html_path() {
        if snapshot.exists() {
            fs::copy(snapshot, case_dir.join("snapshot.html"))?;
        }
    }

    if let Some(document_path) = input.document.relative_path() {
        let absolute = if document_path.is_absolute() {
            document_path.to_path_buf()
        } else {
            input.seed_dir.join(document_path)
        };
        if absolute.exists() {
            fs::copy(absolute, case_dir.join("document.fdir"))?;
        }
    }

    fs::write(
        case_dir.join("actions.json"),
        serde_json::to_string_pretty(actions)?,
    )?;
    fs::write(
        case_dir.join("simulator-response.json"),
        serde_json::to_string_pretty(response)?,
    )?;

    if let Some(crash) = classified_crash {
        fs::write(case_dir.join("asan.txt"), &crash.report.excerpt)?;
        fs::write(
            case_dir.join("metadata.json"),
            format!(
                "{{\n  \"iteration\": {iteration},\n  \"seed_id\": \"{}\",\n  \"crash_type\": \"{}\",\n  \"stack_hash\": \"{:016x}\",\n  \"asan_source\": \"{}\"\n}}\n",
                input.seed_id,
                crash.crash_type.as_str(),
                crash.stack_hash,
                escape_json_string(&crash.report.source),
            ),
        )?;
    }

    Ok(case_dir)
}

fn elapsed_ms(started: Instant) -> u64 {
    started.elapsed().as_millis().try_into().unwrap_or(u64::MAX)
}

fn escape_json_string(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}
