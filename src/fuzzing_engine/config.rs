use std::collections::HashMap;
use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use super::{EngineResult, engine_error};

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub workspace_dir: PathBuf,
    pub out_dir: PathBuf,
    pub crash_dir: PathBuf,
    pub initial_seed_dir: Option<PathBuf>,
    pub sancov_dir: PathBuf,
    pub asan_dir: PathBuf,
    pub dom_generator_dir: PathBuf,
    pub simulator_dir: PathBuf,
    pub uv_cache_dir: PathBuf,
    pub browser_path: String,
    pub browser_kind: String,
    pub max_actions: usize,
    pub seed_inputs: usize,
    pub seed_actions: usize,
    pub max_iterations: Option<u64>,
    pub iteration_timeout_ms: u64,
    pub action_timeout_ms: u64,
    pub page_ready_timeout_ms: u64,
    pub post_actions_settle_ms: u64,
    pub inter_action_delay_ms: u64,
    pub disable_breakpad: bool,
    pub asan_symbolizer_path: Option<String>,
}

impl AppConfig {
    pub fn load() -> EngineResult<Self> {
        let workspace_dir = env::current_dir()?;
        let vars = read_dotenv(&workspace_dir.join(".env"))?;

        if !vars.contains_key("BROWSER_PATH") && vars.contains_key("CHROME_PATH") {
            return Err(engine_error(
                "`CHROME_PATH` is no longer used. Rename it to `BROWSER_PATH` in `.env`.",
            ));
        }

        let browser_path = required_var(&vars, "BROWSER_PATH")?;
        let browser_kind = optional_var(&vars, "BROWSER_KIND").unwrap_or_else(|| "chromium".into());

        let out_dir = path_var(&workspace_dir, &vars, "OUT_DIR", "out");
        let crash_dir = path_var(&workspace_dir, &vars, "CRASH_DIR", "crashes");
        let initial_seed_dir = optional_path_var(&workspace_dir, &vars, "INITIAL_SEED_DIR")
            .or_else(|| optional_path_var(&workspace_dir, &vars, "SEED_DIR"));

        Ok(Self {
            dom_generator_dir: path_var(
                &workspace_dir,
                &vars,
                "DOM_GENERATOR_DIR",
                "src/dom-generator",
            ),
            simulator_dir: path_var(
                &workspace_dir,
                &vars,
                "SIMULATOR_DIR",
                "src/user-interaction-simulator",
            ),
            sancov_dir: out_dir.join("sancov"),
            asan_dir: out_dir.join("asan"),
            uv_cache_dir: out_dir.join("uv-cache"),
            max_actions: usize_var(&vars, "MAX_ACTIONS", 48),
            seed_inputs: usize_var(&vars, "SEED_INPUTS", 1),
            seed_actions: usize_var(&vars, "SEED_ACTIONS", 6),
            max_iterations: max_iterations(&vars),
            iteration_timeout_ms: u64_var(&vars, "ITERATION_TIMEOUT_MS", 12000),
            action_timeout_ms: u64_var(&vars, "ACTION_TIMEOUT_MS", 300),
            page_ready_timeout_ms: u64_var(&vars, "PAGE_READY_TIMEOUT_MS", 120),
            post_actions_settle_ms: u64_var(&vars, "POST_ACTIONS_SETTLE_MS", 120),
            inter_action_delay_ms: u64_var(&vars, "INTER_ACTION_DELAY_MS", 10),
            disable_breakpad: bool_var(&vars, "DISABLE_BREAKPAD", true),
            asan_symbolizer_path: optional_var(&vars, "ASAN_SYMBOLIZER_PATH"),
            workspace_dir,
            out_dir,
            crash_dir,
            initial_seed_dir,
            browser_path,
            browser_kind,
        })
    }

    pub fn ensure_dirs(&self) -> io::Result<()> {
        for dir in [
            &self.out_dir,
            &self.crash_dir,
            &self.sancov_dir,
            &self.asan_dir,
            &self.uv_cache_dir,
        ] {
            fs::create_dir_all(dir)?;
        }
        Ok(())
    }
}

fn read_dotenv(path: &PathBuf) -> EngineResult<HashMap<String, String>> {
    let raw = fs::read_to_string(path).map_err(|error| {
        engine_error(format!(
            "failed to read {}: {error}. Create it from `.env.example`.",
            path.display()
        ))
    })?;

    let mut vars = HashMap::new();
    for (idx, line) in raw.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            return Err(engine_error(format!(
                "invalid .env line {}: expected KEY=VALUE",
                idx + 1
            )));
        };
        let key = key.trim();
        let mut value = value.trim().to_string();
        if value.len() >= 2
            && ((value.starts_with('"') && value.ends_with('"'))
                || (value.starts_with('\'') && value.ends_with('\'')))
        {
            value = value[1..value.len() - 1].to_string();
        }
        vars.insert(key.to_string(), value);
    }
    Ok(vars)
}

fn required_var(vars: &HashMap<String, String>, key: &str) -> EngineResult<String> {
    optional_var(vars, key).ok_or_else(|| engine_error(format!("missing `{key}` in `.env`")))
}

fn optional_var(vars: &HashMap<String, String>, key: &str) -> Option<String> {
    vars.get(key)
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn path_var(root: &Path, vars: &HashMap<String, String>, key: &str, default: &str) -> PathBuf {
    let raw = optional_var(vars, key).unwrap_or_else(|| default.to_string());
    let path = PathBuf::from(raw);
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}

fn optional_path_var(root: &Path, vars: &HashMap<String, String>, key: &str) -> Option<PathBuf> {
    optional_var(vars, key).map(|raw| {
        let path = PathBuf::from(raw);
        if path.is_absolute() {
            path
        } else {
            root.join(path)
        }
    })
}

fn usize_var(vars: &HashMap<String, String>, key: &str, default: usize) -> usize {
    optional_var(vars, key)
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn u64_var(vars: &HashMap<String, String>, key: &str, default: u64) -> u64 {
    optional_var(vars, key)
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

fn max_iterations(vars: &HashMap<String, String>) -> Option<u64> {
    let value = u64_var(vars, "MAX_ITERATIONS", 0);
    if value == 0 { None } else { Some(value) }
}

fn bool_var(vars: &HashMap<String, String>, key: &str, default: bool) -> bool {
    match optional_var(vars, key)
        .unwrap_or_else(|| default.to_string())
        .to_ascii_lowercase()
        .as_str()
    {
        "1" | "true" | "yes" | "y" | "on" => true,
        "0" | "false" | "no" | "n" | "off" => false,
        _ => default,
    }
}
