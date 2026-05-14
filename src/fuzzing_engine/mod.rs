pub mod actions;
pub mod app;
pub mod clients;
pub mod config;
pub mod coverage;
pub mod crash;
pub mod input;
pub mod libafl_executor;
pub mod metrics;
pub mod mutation;
pub mod reporting;
pub mod seed_store;
pub mod testcase_runner;

pub type EngineResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub fn engine_error(message: impl Into<String>) -> Box<dyn std::error::Error + Send + Sync> {
    Box::new(std::io::Error::other(message.into()))
}
