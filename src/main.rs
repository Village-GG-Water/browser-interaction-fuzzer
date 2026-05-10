mod fuzzing_engine;

use fuzzing_engine::EngineResult;
use fuzzing_engine::app::FuzzingApp;
use fuzzing_engine::config::AppConfig;

fn main() {
    if let Err(error) = run() {
        eprintln!("[fatal] {error}");
        std::process::exit(1);
    }
}

fn run() -> EngineResult<()> {
    let config = AppConfig::load()?;
    let mut app = FuzzingApp::new(config)?;
    app.run()
}
