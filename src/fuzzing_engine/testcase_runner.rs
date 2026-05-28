use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime};

use super::EngineResult;
use super::actions::Action;
use super::clients::{
    RunTestcaseRequest, SimulatorClient, SimulatorResponse, optional_path_string,
};
use super::coverage::{
    CoverageTracker, delete_sancov_files, parse_recent_sancov_dir, record_pcs_to_coverage_map,
    reset_coverage_map,
};
use super::crash::{ClassifiedCrash, CrashType, find_and_classify_asan_report};
use super::input::FuzzInput;
use super::lifecycle::{
    HazardSummary, LifecycleTracker, record_hazard_boundaries, reset_hazard_map,
};

#[derive(Debug)]
pub struct ExecutionOutcome {
    pub response: SimulatorResponse,
    pub new_coverage_edges: usize,
    pub hazard_summary: HazardSummary,
    pub classified_crash: Option<ClassifiedCrash>,
    pub timed_out: bool,
}

impl ExecutionOutcome {
    pub fn objective_crash_type(&self) -> Option<CrashType> {
        if let Some(crash) = &self.classified_crash {
            Some(crash.crash_type)
        } else if self.response.status == "crash" {
            Some(CrashType::Unknown)
        } else {
            None
        }
    }

    pub fn crash_type(&self) -> Option<CrashType> {
        self.objective_crash_type()
    }

    pub fn is_crash(&self) -> bool {
        self.objective_crash_type().is_some()
    }
}

pub struct TestcaseRunner {
    simulator: SimulatorClient,
    sancov_dir: PathBuf,
    asan_dir: PathBuf,
    lifecycle: LifecycleTracker,
}

impl TestcaseRunner {
    pub fn new(simulator: SimulatorClient, sancov_dir: PathBuf, asan_dir: PathBuf) -> Self {
        Self {
            simulator,
            sancov_dir,
            asan_dir,
            lifecycle: LifecycleTracker::default(),
        }
    }

    pub fn run(
        &mut self,
        iteration: u64,
        input: &FuzzInput,
        coverage: &mut CoverageTracker,
    ) -> EngineResult<ExecutionOutcome> {
        reset_coverage_map();
        reset_hazard_map();
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
        record_pcs_to_coverage_map(&pcs);
        let new_coverage_edges = coverage.update(&pcs);
        delete_sancov_files(&parsed_files);

        let mut response = response;
        response.timings.asan_scan_ms = asan_scan_ms;
        response.timings.sancov_parse_ms = sancov_parse_ms;
        response.timings.iteration_total_ms = elapsed_ms(iteration_started);
        let hazard_summary =
            self.lifecycle
                .evaluate(&input.actions, &response, &input.interactables);
        record_hazard_boundaries(&hazard_summary);

        Ok(ExecutionOutcome {
            timed_out: response.status == "timeout",
            response,
            new_coverage_edges,
            hazard_summary,
            classified_crash,
        })
    }
}

pub fn save_crash_artifacts(
    session_id: &str,
    crash_session_dir: &Path,
    iteration: u64,
    input: &FuzzInput,
    actions: &[Action],
    response: &SimulatorResponse,
    hazard_summary: &HazardSummary,
    classified_crash: Option<&ClassifiedCrash>,
) -> EngineResult<PathBuf> {
    let case_dir = crash_session_dir.join(format!("crash_{iteration:06}"));
    fs::create_dir_all(&case_dir)?;

    if let Some(snapshot) = input.html_path()
        && snapshot.exists()
    {
        fs::copy(snapshot, case_dir.join("snapshot.html"))?;
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
    fs::write(
        case_dir.join("hazard-summary.json"),
        serde_json::to_string_pretty(hazard_summary)?,
    )?;

    let metadata = if let Some(crash) = classified_crash {
        fs::write(case_dir.join("asan.txt"), &crash.report.excerpt)?;
        serde_json::json!({
            "session_id": session_id,
            "iteration": iteration,
            "seed_id": input.seed_id,
            "status": response.status,
            "crash_type": crash.crash_type.as_str(),
            "stack_hash": format!("{:016x}", crash.stack_hash),
            "asan_source": crash.report.source,
            "hazard_summary": hazard_summary,
        })
    } else {
        serde_json::json!({
            "session_id": session_id,
            "iteration": iteration,
            "seed_id": input.seed_id,
            "status": response.status,
            "crash_type": null,
            "hazard_summary": hazard_summary,
        })
    };
    fs::write(
        case_dir.join("metadata.json"),
        serde_json::to_string_pretty(&metadata)?,
    )?;

    Ok(case_dir)
}

fn elapsed_ms(started: Instant) -> u64 {
    started.elapsed().as_millis().try_into().unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::super::crash::AsanReport;
    use super::super::metrics::IterationTimings;
    use super::*;

    fn outcome(status: &str, classified_crash: Option<ClassifiedCrash>) -> ExecutionOutcome {
        ExecutionOutcome {
            response: SimulatorResponse {
                status: status.to_string(),
                reason: None,
                actions_attempted: 0,
                actions_succeeded: 0,
                selector_fallbacks: 0,
                slow_actions: 0,
                timings: IterationTimings::default(),
                action_trace: Vec::new(),
            },
            new_coverage_edges: 0,
            hazard_summary: HazardSummary::default(),
            classified_crash,
            timed_out: status == "timeout",
        }
    }

    fn classified_crash(crash_type: CrashType) -> ClassifiedCrash {
        ClassifiedCrash {
            crash_type,
            stack_hash: 0,
            report: AsanReport {
                source: "asan.log".to_string(),
                excerpt: "ERROR: AddressSanitizer".to_string(),
            },
        }
    }

    #[test]
    fn bare_timeout_is_not_an_objective_crash() {
        let outcome = outcome("timeout", None);

        assert!(!outcome.is_crash());
        assert_eq!(outcome.objective_crash_type(), None);
    }

    #[test]
    fn timeout_with_asan_report_is_an_objective_crash() {
        let outcome = outcome(
            "timeout",
            Some(classified_crash(CrashType::HeapUseAfterFree)),
        );

        assert!(outcome.is_crash());
        assert_eq!(
            outcome.objective_crash_type(),
            Some(CrashType::HeapUseAfterFree)
        );
    }

    #[test]
    fn simulator_crash_status_is_an_objective_crash() {
        let outcome = outcome("crash", None);

        assert!(outcome.is_crash());
        assert_eq!(outcome.objective_crash_type(), Some(CrashType::Unknown));
    }

    #[test]
    fn ok_status_is_not_an_objective_crash() {
        let outcome = outcome("ok", None);

        assert!(!outcome.is_crash());
        assert_eq!(outcome.objective_crash_type(), None);
    }
}
