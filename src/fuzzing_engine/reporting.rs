use super::config::AppConfig;
use super::metrics::RunMetrics;

pub struct Reporter;

impl Reporter {
    pub fn print_config(config: &AppConfig) {
        println!("[config] workspace={}", config.workspace_dir.display());
        println!("[config] browser_kind={}", config.browser_kind);
        println!("[config] browser_path={}", config.browser_path);
        println!(
            "[config] dom_generator={}",
            config.dom_generator_dir.display()
        );
        println!("[config] simulator={}", config.simulator_dir.display());
        match &config.initial_seed_dir {
            Some(seed_dir) => println!("[config] initial_seed_dir={}", seed_dir.display()),
            None => println!("[config] initial_seed_dir=<generated>"),
        }
        println!("[config] libafl_corpus=in-memory");
        println!("[config] out={}", config.out_dir.display());
    }

    pub fn session_started(session_id: &str, crash_session_dir: &std::path::Path) {
        println!(
            "[session] id={session_id} crashes={}",
            crash_session_dir.display()
        );
    }

    pub fn seed_loaded(seed_id: &str, source_kind: &str) {
        println!("[seed] loaded {seed_id} source={source_kind}");
    }

    pub fn generated_seed(seed_id: &str) {
        println!("[seed] generated {seed_id}");
    }

    pub fn new_coverage(new_edges: usize) {
        println!("[coverage] new edges={new_edges}");
    }

    pub fn crash(iteration: u64, crash_type: &str, crash_dir: &std::path::Path) {
        println!(
            "[crash] iteration={iteration} type={crash_type} saved={}",
            crash_dir.display()
        );
    }

    pub fn progress(metrics: &RunMetrics) {
        println!(
            "[progress] iter={} corpus={} new_cov={} crashes={} infra={} actions={} ok_actions={} fallbacks={} slow_actions={}",
            metrics.iterations,
            metrics.corpus_size,
            metrics.new_coverage_events,
            metrics.crashes,
            metrics.infra_errors,
            metrics.last_actions,
            metrics.last_action_successes,
            metrics.last_selector_fallbacks,
            metrics.last_slow_actions,
        );
        Self::timing(metrics);
    }

    pub fn timing(metrics: &RunMetrics) {
        let t = metrics.timing_summary();
        println!(
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
        println!(
            "[summary] iter={} corpus={} new_cov={} crashes={} infra={}",
            metrics.iterations,
            metrics.corpus_size,
            metrics.new_coverage_events,
            metrics.crashes,
            metrics.infra_errors,
        );
    }
}
