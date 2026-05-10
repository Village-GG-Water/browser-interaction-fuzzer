pub mod actions;
pub mod app;
pub mod clients;
pub mod config;
pub mod corpus;
pub mod coverage;
pub mod crash;
pub mod executor;
pub mod input;
pub mod metrics;
pub mod mutation;
pub mod reporting;

pub type EngineResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub fn engine_error(message: impl Into<String>) -> Box<dyn std::error::Error + Send + Sync> {
    Box::new(std::io::Error::new(
        std::io::ErrorKind::Other,
        message.into(),
    ))
}
