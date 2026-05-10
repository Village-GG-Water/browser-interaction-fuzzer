use std::collections::hash_map::DefaultHasher;
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::Path;
use std::time::SystemTime;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CrashType {
    HeapUseAfterFree,
    HeapBufferOverflow,
    StackBufferOverflow,
    GlobalBufferOverflow,
    UseAfterReturn,
    UseAfterScope,
    DoubleFree,
    AccessViolation,
    SegmentationFault,
    DebugAssertion,
    CheckFailure,
    Breakpoint,
    Timeout,
    Unknown,
}

impl CrashType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::HeapUseAfterFree => "heap-use-after-free",
            Self::HeapBufferOverflow => "heap-buffer-overflow",
            Self::StackBufferOverflow => "stack-buffer-overflow",
            Self::GlobalBufferOverflow => "global-buffer-overflow",
            Self::UseAfterReturn => "stack-use-after-return",
            Self::UseAfterScope => "stack-use-after-scope",
            Self::DoubleFree => "double-free",
            Self::AccessViolation => "access-violation",
            Self::SegmentationFault => "segmentation-fault",
            Self::DebugAssertion => "debug-assertion",
            Self::CheckFailure => "check-failure",
            Self::Breakpoint => "breakpoint",
            Self::Timeout => "timeout",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone)]
pub struct AsanReport {
    pub source: String,
    pub excerpt: String,
}

#[derive(Debug, Clone)]
pub struct ClassifiedCrash {
    pub crash_type: CrashType,
    pub stack_hash: u64,
    pub report: AsanReport,
}

pub fn classify_crash(asan_log: &str) -> CrashType {
    let lower = asan_log.to_lowercase();
    if lower.contains("heap-use-after-free") {
        return CrashType::HeapUseAfterFree;
    }
    if lower.contains("heap-buffer-overflow") {
        return CrashType::HeapBufferOverflow;
    }
    if lower.contains("stack-buffer-overflow") {
        return CrashType::StackBufferOverflow;
    }
    if lower.contains("global-buffer-overflow") {
        return CrashType::GlobalBufferOverflow;
    }
    if lower.contains("stack-use-after-return") {
        return CrashType::UseAfterReturn;
    }
    if lower.contains("stack-use-after-scope") {
        return CrashType::UseAfterScope;
    }
    if lower.contains("double-free") || lower.contains("attempting free on address") {
        return CrashType::DoubleFree;
    }
    if lower.contains("breakdebugger") {
        return CrashType::DebugAssertion;
    }
    if lower.contains("check failure") || lower.contains("check failed") {
        return CrashType::CheckFailure;
    }
    if lower.contains("breakpoint on unknown address") {
        return CrashType::Breakpoint;
    }
    if lower.contains("access-violation") {
        return CrashType::AccessViolation;
    }
    if lower.contains("segmentation fault") || lower.contains("segv") {
        return CrashType::SegmentationFault;
    }
    if lower.contains("timeout") || lower.contains("timed out") {
        return CrashType::Timeout;
    }
    CrashType::Unknown
}

pub fn find_and_classify_asan_report(
    asan_dir: &Path,
    started_at: SystemTime,
) -> Option<ClassifiedCrash> {
    let report = find_asan_report(asan_dir, started_at)?;
    Some(ClassifiedCrash {
        crash_type: classify_crash(&report.excerpt),
        stack_hash: hash_stack_trace(&report.excerpt),
        report,
    })
}

fn find_asan_report(asan_dir: &Path, started_at: SystemTime) -> Option<AsanReport> {
    if !asan_dir.exists() {
        return None;
    }

    let mut recent_files = Vec::new();
    for entry in fs::read_dir(asan_dir).ok()? {
        let entry = entry.ok()?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let modified = entry.metadata().ok()?.modified().ok()?;
        if modified >= started_at {
            recent_files.push((modified, path));
        }
    }
    recent_files.sort_by(|left, right| right.0.cmp(&left.0));

    for (_, path) in recent_files {
        let text = String::from_utf8_lossy(&fs::read(&path).ok()?).to_string();
        if let Some(excerpt) = extract_asan_excerpt(&text) {
            return Some(AsanReport {
                source: path.display().to_string(),
                excerpt,
            });
        }
    }
    None
}

fn extract_asan_excerpt(text: &str) -> Option<String> {
    let lines: Vec<&str> = text.lines().collect();
    for (idx, line) in lines.iter().enumerate() {
        if line.contains("ERROR: AddressSanitizer")
            || line.contains("SUMMARY: AddressSanitizer")
            || line.contains("AddressSanitizer:")
        {
            let start = idx.saturating_sub(2);
            let end = (idx + 180).min(lines.len());
            return Some(lines[start..end].join("\n"));
        }
    }
    None
}

fn hash_stack_trace(asan_log: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    let mut frames = Vec::new();
    let mut addresses = Vec::new();

    for line in asan_log.lines() {
        for token in line.split_whitespace() {
            let trimmed = token.trim_matches(|ch: char| !ch.is_ascii_hexdigit() && ch != 'x');
            if trimmed.starts_with("0x") && trimmed[2..].chars().all(|ch| ch.is_ascii_hexdigit()) {
                addresses.push(trimmed.to_string());
            }
        }

        if let Some(stripped) = line.trim().strip_prefix('#') {
            if let Some(pos) = stripped.find(" in ") {
                let after = &stripped[pos + 4..];
                let frame = after
                    .split_once('(')
                    .map(|(func, _)| func)
                    .or_else(|| after.split_once(" D:").map(|(func, _)| func))
                    .or_else(|| after.split_once(" C:").map(|(func, _)| func))
                    .unwrap_or(after)
                    .trim();
                if !frame.is_empty() && !frame.starts_with("0x") {
                    frames.push(frame.to_string());
                }
            }
        }
    }

    if frames.is_empty() {
        for address in addresses.iter().take(10) {
            address.hash(&mut hasher);
        }
    } else {
        for frame in frames.iter().take(10) {
            frame.hash(&mut hasher);
        }
    }

    hasher.finish()
}
