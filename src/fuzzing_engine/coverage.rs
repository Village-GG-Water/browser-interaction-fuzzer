use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

const SANCOV_MAGIC: u64 = 0xC0BFFFFFFFFFFF64;
const DEFAULT_MAP_SIZE: usize = 1 << 26;

pub fn parse_sancov_file(path: &Path) -> io::Result<Vec<u64>> {
    let data = fs::read(path)?;
    if data.len() < 16 {
        return Ok(Vec::new());
    }

    let magic = u64::from_le_bytes(data[0..8].try_into().unwrap());
    if magic != SANCOV_MAGIC {
        return Ok(Vec::new());
    }

    Ok(data[16..]
        .chunks_exact(8)
        .map(|chunk| u64::from_le_bytes(chunk.try_into().unwrap()))
        .collect())
}

pub fn parse_recent_sancov_dir(
    dir: &Path,
    started_at: SystemTime,
) -> io::Result<(Vec<u64>, Vec<PathBuf>)> {
    let mut pcs = Vec::new();
    let mut parsed_files = Vec::new();

    if !dir.exists() {
        return Ok((pcs, parsed_files));
    }

    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("sancov") {
            continue;
        }
        if entry.metadata()?.modified()? < started_at {
            continue;
        }

        pcs.extend(parse_sancov_file(&path)?);
        parsed_files.push(path);
    }

    Ok((pcs, parsed_files))
}

pub fn delete_sancov_files(files: &[PathBuf]) {
    for path in files {
        let _ = fs::remove_file(path);
    }
}

pub fn coverage_index(pc: u64, map_len: usize) -> usize {
    let mixed = pc.wrapping_mul(0x517c_c1b7_2722_0a95);
    (mixed % map_len as u64) as usize
}

#[derive(Debug)]
pub struct CoverageTracker {
    seen_indices: HashSet<usize>,
    map_len: usize,
}

impl CoverageTracker {
    pub fn new() -> Self {
        Self {
            seen_indices: HashSet::new(),
            map_len: DEFAULT_MAP_SIZE,
        }
    }

    pub fn update(&mut self, pcs: &[u64]) -> usize {
        let mut new_edges = 0;
        for &pc in pcs {
            let idx = coverage_index(pc, self.map_len);
            if self.seen_indices.insert(idx) {
                new_edges += 1;
            }
        }
        new_edges
    }
}

#[cfg(test)]
mod tests {
    use super::CoverageTracker;

    #[test]
    fn tracker_counts_only_new_indices() {
        let mut tracker = CoverageTracker::new();

        assert_eq!(tracker.update(&[0x1000, 0x2000]), 2);
        assert_eq!(tracker.update(&[0x1000]), 0);
    }
}
