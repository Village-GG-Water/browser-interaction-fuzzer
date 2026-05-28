use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};

use super::actions::{Action, ActionKind};
use super::clients::{ActionTargetTrace, SimulatorResponse};
use super::mutation::InteractableMetadata;

pub const HAZARD_MAP_SIZE: usize = 3;
pub static mut HAZARD_MAP: [u8; HAZARD_MAP_SIZE] = [0; HAZARD_MAP_SIZE];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HazardBoundary {
    InvalidatedToAsync,
    AsyncToStaleReuse,
    RestoredToStaleReuse,
}

impl HazardBoundary {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::InvalidatedToAsync => "invalidated_to_async",
            Self::AsyncToStaleReuse => "async_to_stale_reuse",
            Self::RestoredToStaleReuse => "restored_to_stale_reuse",
        }
    }

    fn map_index(self) -> usize {
        match self {
            Self::InvalidatedToAsync => 0,
            Self::AsyncToStaleReuse => 1,
            Self::RestoredToStaleReuse => 2,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct HazardSummary {
    pub boundaries: Vec<HazardBoundary>,
    pub new_boundaries: Vec<HazardBoundary>,
    pub stale_reuse_candidates: usize,
    pub invalidated_targets: usize,
    pub last_boundary: Option<HazardBoundary>,
}

impl HazardSummary {
    pub fn has_new_boundary(&self) -> bool {
        !self.new_boundaries.is_empty()
    }
}

#[derive(Debug, Default)]
pub struct LifecycleTracker {
    seen: HashSet<HazardBoundary>,
}

impl LifecycleTracker {
    pub fn evaluate(
        &mut self,
        actions: &[Action],
        response: &SimulatorResponse,
        interactables: &[InteractableMetadata],
    ) -> HazardSummary {
        let mut summary = score_hazards(actions, response, interactables);
        summary.new_boundaries = summary
            .boundaries
            .iter()
            .copied()
            .filter(|boundary| self.seen.insert(*boundary))
            .collect();
        summary
    }
}

#[derive(Debug, Default)]
struct TargetState {
    invalidated: bool,
    async_pending: bool,
    stale_reused: bool,
}

pub fn score_hazards(
    actions: &[Action],
    response: &SimulatorResponse,
    interactables: &[InteractableMetadata],
) -> HazardSummary {
    let metadata = metadata_by_selector(interactables);
    let mut states: HashMap<String, TargetState> = HashMap::new();
    let mut boundaries = HashSet::new();

    for trace in &response.action_trace {
        let action = actions.get(trace.index);
        let selector = trace_selector(trace).or_else(|| {
            action
                .and_then(|action| action.target.as_ref())
                .and_then(|target| target.selector())
                .map(str::to_string)
        });

        if let Some(selector) = selector {
            let state = states.entry(selector.clone()).or_default();
            let meta = metadata.get(selector.as_str());
            let metadata_invalidates = meta
                .is_some_and(|item| item.invalidates_self || item.invalidates_dom)
                && action.is_some_and(is_trigger_action);
            let trace_invalidates =
                trace.exists_before == Some(true) && trace.exists_after == Some(false);

            if metadata_invalidates || trace_invalidates {
                state.invalidated = true;
                if meta.is_some_and(|item| item.has_async_boundary) {
                    state.async_pending = true;
                    boundaries.insert(HazardBoundary::InvalidatedToAsync);
                }
            }

            let stale_reuse = state.invalidated
                && (trace.exists_before == Some(false)
                    || trace.fallback_used
                    || action
                        .and_then(|action| action.target.as_ref())
                        .is_some_and(|target| {
                            target.uses_cached_point() || target.disables_fallback()
                        }));
            if stale_reuse {
                state.stale_reused = true;
                if state.async_pending {
                    boundaries.insert(HazardBoundary::AsyncToStaleReuse);
                }
            }
        }

        if action.is_some_and(|action| action.kind == ActionKind::Sleep) {
            for state in states.values_mut().filter(|state| state.invalidated) {
                state.async_pending = true;
                boundaries.insert(HazardBoundary::InvalidatedToAsync);
            }
        }
    }

    let mut boundaries = boundaries.into_iter().collect::<Vec<_>>();
    boundaries.sort_by_key(|boundary| boundary.map_index());
    let stale_reuse_candidates = states.values().filter(|state| state.stale_reused).count();
    let invalidated_targets = states.values().filter(|state| state.invalidated).count();
    let last_boundary = boundaries.last().copied();

    HazardSummary {
        boundaries,
        new_boundaries: Vec::new(),
        stale_reuse_candidates,
        invalidated_targets,
        last_boundary,
    }
}

pub fn reset_hazard_map() {
    unsafe {
        let base = std::ptr::addr_of_mut!(HAZARD_MAP) as *mut u8;
        std::ptr::write_bytes(base, 0, HAZARD_MAP_SIZE);
    }
}

pub fn record_hazard_boundaries(summary: &HazardSummary) {
    unsafe {
        let base = std::ptr::addr_of_mut!(HAZARD_MAP) as *mut u8;
        for boundary in &summary.boundaries {
            *base.add(boundary.map_index()) = 1;
        }
    }
}

fn metadata_by_selector(
    interactables: &[InteractableMetadata],
) -> HashMap<&str, &InteractableMetadata> {
    interactables
        .iter()
        .map(|item| (item.selector.as_str(), item))
        .collect()
}

fn trace_selector(trace: &super::clients::ActionTraceEntry) -> Option<String> {
    match trace.target.as_ref()? {
        ActionTargetTrace::Dom { selector, .. } => Some(selector.clone()),
        ActionTargetTrace::BrowserUi { .. } => None,
    }
}

fn is_trigger_action(action: &Action) -> bool {
    matches!(
        action.kind,
        ActionKind::Click
            | ActionKind::DoubleClick
            | ActionKind::RightClick
            | ActionKind::Focus
            | ActionKind::Hover
            | ActionKind::TypeText
            | ActionKind::Clear
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fuzzing_engine::actions::{Action, ActionTarget};
    use crate::fuzzing_engine::clients::ActionTraceEntry;

    #[test]
    fn scores_async_stale_reuse_boundary_once() {
        let actions = vec![
            Action::click(ActionTarget::dom("#victim")),
            Action::sleep(16),
            Action::click(ActionTarget::dom_cached_point_no_fallback("#victim")),
        ];
        let response = SimulatorResponse {
            status: "ok".to_string(),
            reason: None,
            actions_attempted: 3,
            actions_succeeded: 3,
            selector_fallbacks: 0,
            slow_actions: 0,
            timings: Default::default(),
            browser_session: None,
            action_trace: vec![
                trace(0, "#victim", true, false, false),
                trace(1, "#victim", false, false, false),
                trace(2, "#victim", false, false, false),
            ],
        };
        let interactables = vec![InteractableMetadata {
            selector: "#victim".to_string(),
            invalidates_self: true,
            has_handler: true,
            ..InteractableMetadata::default()
        }];
        let mut tracker = LifecycleTracker::default();

        let first = tracker.evaluate(&actions, &response, &interactables);
        let second = tracker.evaluate(&actions, &response, &interactables);

        assert_eq!(
            first.boundaries,
            vec![
                HazardBoundary::InvalidatedToAsync,
                HazardBoundary::AsyncToStaleReuse
            ]
        );
        assert_eq!(first.new_boundaries.len(), 2);
        assert!(second.new_boundaries.is_empty());
    }

    fn trace(
        index: usize,
        selector: &str,
        exists_before: bool,
        exists_after: bool,
        fallback_used: bool,
    ) -> ActionTraceEntry {
        ActionTraceEntry {
            index,
            kind: Some("click".to_string()),
            target: Some(ActionTargetTrace::Dom {
                selector: selector.to_string(),
                resolution: None,
                fallback: None,
            }),
            ok: true,
            fallback_used,
            elapsed_ms: 1,
            exists_before: Some(exists_before),
            exists_after: Some(exists_after),
            url_before: "about:blank".to_string(),
            url_after: "about:blank".to_string(),
        }
    }
}
