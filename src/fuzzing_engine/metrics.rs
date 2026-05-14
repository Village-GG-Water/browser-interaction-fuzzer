use serde::{Deserialize, Serialize};

#[derive(Debug, Default, Clone, Copy, Serialize, Deserialize)]
pub struct IterationTimings {
    #[serde(default)]
    pub launch_ms: u64,
    #[serde(default)]
    pub load_ms: u64,
    #[serde(default)]
    pub actions_ms: u64,
    #[serde(default)]
    pub close_ms: u64,
    #[serde(default)]
    pub simulator_total_ms: u64,
    #[serde(default)]
    pub asan_scan_ms: u64,
    #[serde(default)]
    pub sancov_parse_ms: u64,
    #[serde(default)]
    pub iteration_total_ms: u64,
}

#[derive(Debug, Default)]
pub struct RunMetrics {
    pub iterations: u64,
    pub corpus_size: usize,
    pub new_coverage_events: u64,
    pub crashes: u64,
    pub infra_errors: u64,
    pub last_actions: usize,
    pub last_action_successes: u64,
    pub last_selector_fallbacks: u64,
    pub last_slow_actions: u64,
    pub recent_timings: Vec<IterationTimings>,
}

impl RunMetrics {
    pub fn record_iteration(
        &mut self,
        actions: usize,
        action_successes: u64,
        selector_fallbacks: u64,
        slow_actions: u64,
        timings: IterationTimings,
    ) {
        self.iterations += 1;
        self.last_actions = actions;
        self.last_action_successes = action_successes;
        self.last_selector_fallbacks = selector_fallbacks;
        self.last_slow_actions = slow_actions;
        self.recent_timings.push(timings);
        if self.recent_timings.len() > 100 {
            self.recent_timings.remove(0);
        }
    }

    pub fn timing_summary(&self) -> TimingSummary {
        TimingSummary {
            total: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.iteration_total_ms)
                    .collect::<Vec<_>>(),
            ),
            simulator_total: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.simulator_total_ms)
                    .collect::<Vec<_>>(),
            ),
            launch: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.launch_ms)
                    .collect::<Vec<_>>(),
            ),
            load: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.load_ms)
                    .collect::<Vec<_>>(),
            ),
            actions: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.actions_ms)
                    .collect::<Vec<_>>(),
            ),
            close: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.close_ms)
                    .collect::<Vec<_>>(),
            ),
            asan_scan: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.asan_scan_ms)
                    .collect::<Vec<_>>(),
            ),
            sancov_parse: avg_p95(
                &self
                    .recent_timings
                    .iter()
                    .map(|timing| timing.sancov_parse_ms)
                    .collect::<Vec<_>>(),
            ),
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct AvgP95 {
    pub avg: u64,
    pub p95: u64,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct TimingSummary {
    pub total: AvgP95,
    pub simulator_total: AvgP95,
    pub launch: AvgP95,
    pub load: AvgP95,
    pub actions: AvgP95,
    pub close: AvgP95,
    pub asan_scan: AvgP95,
    pub sancov_parse: AvgP95,
}

fn avg_p95(values: &[u64]) -> AvgP95 {
    if values.is_empty() {
        return AvgP95::default();
    }
    let avg = values.iter().sum::<u64>() / values.len() as u64;
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let idx = ((sorted.len() * 95).div_ceil(100)).saturating_sub(1);
    AvgP95 {
        avg,
        p95: sorted[idx],
    }
}

#[cfg(test)]
mod tests {
    use super::avg_p95;

    #[test]
    fn avg_p95_handles_sorted_index() {
        let summary = avg_p95(&[10, 20, 30, 40]);

        assert_eq!(summary.avg, 25);
        assert_eq!(summary.p95, 40);
    }
}
