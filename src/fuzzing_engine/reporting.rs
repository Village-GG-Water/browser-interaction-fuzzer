use super::config::AppConfig;
use super::metrics::RunMetrics;

macro_rules! report {
    ($($arg:tt)*) => {
        println!("[{}] {}", local_timestamp(), format_args!($($arg)*))
    };
}

pub struct Reporter;

impl Reporter {
    pub fn print_config(config: &AppConfig) {
        report!("[config] workspace={}", config.workspace_dir.display());
        report!("[config] browser_kind={}", config.browser_kind);
        report!("[config] browser_path={}", config.browser_path);
        report!(
            "[config] dom_generator={}",
            config.dom_generator_dir.display()
        );
        report!("[config] simulator={}", config.simulator_dir.display());
        match &config.initial_seed_dir {
            Some(seed_dir) => report!("[config] initial_seed_dir={}", seed_dir.display()),
            None => report!("[config] initial_seed_dir=<generated>"),
        }
        report!("[config] libafl_corpus=in-memory");
        report!("[config] out={}", config.out_dir.display());
    }

    pub fn session_started(session_id: &str, crash_session_dir: &std::path::Path) {
        report!(
            "[session] id={session_id} crashes={}",
            crash_session_dir.display()
        );
    }

    pub fn seed_loaded(seed_id: &str, source_kind: &str) {
        report!("[seed] loaded {seed_id} source={source_kind}");
    }

    pub fn generated_seed(seed_id: &str) {
        report!("[seed] generated {seed_id}");
    }

    pub fn new_coverage(iteration: u64, new_edges: usize) {
        report!("[coverage] iteration={iteration} new_edges={new_edges}");
    }

    pub fn new_hazard(iteration: u64, boundary: &str, stale_reuse_candidates: usize) {
        report!(
            "[hazard] iteration={iteration} boundary={boundary} stale_reuse_candidates={stale_reuse_candidates}"
        );
    }

    pub fn crash(iteration: u64, crash_type: &str, crash_dir: &std::path::Path) {
        report!(
            "[crash] iteration={iteration} type={crash_type} saved={}",
            crash_dir.display()
        );
    }

    pub fn progress(metrics: &RunMetrics) {
        report!(
            "[progress] iter={} corpus={} new_cov={} new_hazard={} crashes={} infra={} actions={} ok_actions={} fallbacks={} slow_actions={} stale_reuse={}{}{}",
            metrics.iterations,
            metrics.corpus_size,
            metrics.new_coverage_events,
            metrics.new_hazard_events,
            metrics.crashes,
            metrics.infra_errors,
            metrics.last_actions,
            metrics.last_action_successes,
            metrics.last_selector_fallbacks,
            metrics.last_slow_actions,
            metrics.last_stale_reuse_candidates,
            hazard_suffix(metrics),
            policy_suffix(metrics),
        );
        Self::timing(metrics);
    }

    pub fn timing(metrics: &RunMetrics) {
        let t = metrics.timing_summary();
        report!(
            "[timing] avg/p95 ms total={}/{} simulator={}/{} launch={}/{} load={}/{} actions={}/{} close={}/{} asan={}/{} sancov={}/{}",
            t.total.avg,
            t.total.p95,
            t.simulator_total.avg,
            t.simulator_total.p95,
            t.launch.avg,
            t.launch.p95,
            t.load.avg,
            t.load.p95,
            t.actions.avg,
            t.actions.p95,
            t.close.avg,
            t.close.p95,
            t.asan_scan.avg,
            t.asan_scan.p95,
            t.sancov_parse.avg,
            t.sancov_parse.p95,
        );
    }

    pub fn summary(metrics: &RunMetrics) {
        report!(
            "[summary] iter={} corpus={} new_cov={} new_hazard={} crashes={} infra={}{}{}",
            metrics.iterations,
            metrics.corpus_size,
            metrics.new_coverage_events,
            metrics.new_hazard_events,
            metrics.crashes,
            metrics.infra_errors,
            hazard_suffix(metrics),
            policy_suffix(metrics),
        );
    }
}

fn hazard_suffix(metrics: &RunMetrics) -> String {
    metrics
        .last_hazard_boundary
        .as_ref()
        .map(|boundary| format!(" last_hazard={boundary}"))
        .unwrap_or_default()
}

fn local_timestamp() -> String {
    chrono::Local::now()
        .format("%Y-%m-%d %H:%M:%S%.3f %:z")
        .to_string()
}

fn policy_suffix(metrics: &RunMetrics) -> String {
    let Some(snapshot) = metrics.policy_snapshot else {
        return String::new();
    };
    format!(
        " action_budget={} dom_budget=elements:{},handlers:{},css:{} stagnation={} phase=dom:{}/{} user:{}/{}",
        snapshot.action_budget,
        snapshot.dom_budget.max_elements,
        snapshot.dom_budget.max_handlers,
        snapshot.dom_budget.max_css_rules,
        snapshot.stagnation_runs,
        snapshot.phase_stats.dom_successes,
        snapshot.phase_stats.dom_failures,
        snapshot.phase_stats.user_successes,
        snapshot.phase_stats.user_failures,
    )
}
