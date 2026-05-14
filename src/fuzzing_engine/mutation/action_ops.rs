use rand::Rng;
use serde::{Deserialize, Serialize};

use super::interaction_fsa;
use crate::fuzzing_engine::actions::{Action, ActionKind, ActionTarget};

#[derive(Debug, Clone, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct InteractableMetadata {
    pub selector: String,
    pub tag: String,
    #[serde(default)]
    pub events: Vec<String>,
    #[serde(default)]
    pub is_text_input: bool,
    #[serde(default)]
    pub is_draggable: bool,
    #[serde(default)]
    pub is_drop_target: bool,
    #[serde(default)]
    pub is_focusable: bool,
    #[serde(default)]
    pub has_handler: bool,
    #[serde(default)]
    pub invalidates_self: bool,
    #[serde(default)]
    pub invalidates_dom: bool,
    #[serde(default)]
    pub has_async_boundary: bool,
}

impl InteractableMetadata {
    pub fn is_lifecycle_hazard(&self) -> bool {
        self.invalidates_self || self.invalidates_dom || self.has_async_boundary
    }
}

const FALLBACK_SELECTORS: [&str; 12] = [
    "button",
    "input",
    "textarea",
    "div",
    "iframe",
    "a",
    "img",
    "canvas",
    "video",
    "audio",
    "[contenteditable]",
    "[draggable]",
];

const TEXTS: [&str; 7] = [
    "test",
    "fuzz",
    "x",
    "hello",
    "123",
    "<script>alert(1)</script>",
    "",
];

const KEYS: [&str; 7] = [
    "Enter",
    "Escape",
    "Tab",
    "Backspace",
    "Delete",
    "ArrowUp",
    "ArrowDown",
];

pub fn selectors_from_interactables(interactables: &[InteractableMetadata]) -> Vec<String> {
    let mut selectors = Vec::new();
    for item in interactables {
        if !item.selector.is_empty() && !selectors.contains(&item.selector) {
            selectors.push(item.selector.clone());
        }
    }
    selectors
}

pub fn action_sequence_from_metadata<R: Rng + ?Sized>(
    rng: &mut R,
    base_count: usize,
    interactables: &[InteractableMetadata],
    action_hints: &[Action],
) -> Vec<Action> {
    if rng.gen_range(0..100) >= 15 {
        return interaction_fsa::generate_action_sequence(
            rng,
            base_count,
            interactables,
            action_hints,
        );
    }

    let max_len = base_count.max(1);
    let target_len = rng.gen_range(1..=max_len);
    let fallback_selectors = selectors_from_interactables(interactables);
    let mut actions = Vec::with_capacity(target_len);

    for hint in action_hints.iter().take(target_len) {
        actions.push(hint.clone());
    }

    while actions.len() < target_len {
        actions.push(random_action_from_metadata(
            rng,
            interactables,
            &fallback_selectors,
        ));
    }

    actions
}

#[cfg(test)]
mod tests {
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    use super::*;

    #[test]
    fn initial_actions_stay_within_seed_budget_even_with_many_hints() {
        let mut rng = StdRng::seed_from_u64(4);
        let hints = vec![Action::scroll(0, 1); 10];

        for _ in 0..32 {
            let actions = action_sequence_from_metadata(&mut rng, 3, &[], &hints);
            assert!((1..=3).contains(&actions.len()));
        }
    }

    #[test]
    fn action_insert_respects_current_budget() {
        let mut rng = StdRng::seed_from_u64(9);
        let mut actions = vec![
            Action::scroll(0, 1),
            Action::scroll(0, 2),
            Action::scroll(0, 3),
        ];

        for _ in 0..32 {
            mutate_action_sequence(&mut rng, &mut actions, 3, &[]);
            assert!(actions.len() <= 3);
        }
    }

    #[test]
    fn stale_reuse_suffix_uses_cached_point_without_fallback() {
        let mut rng = StdRng::seed_from_u64(11);
        let mut actions = vec![Action::scroll(0, 1)];
        let interactables = vec![InteractableMetadata {
            selector: "#victim".to_string(),
            tag: "button".to_string(),
            events: vec!["click".to_string()],
            is_focusable: true,
            has_handler: true,
            invalidates_self: true,
            ..InteractableMetadata::default()
        }];

        assert!(insert_stale_reuse_suffix(
            &mut rng,
            &mut actions,
            4,
            &interactables
        ));

        assert_eq!(actions.len(), 4);
        assert_eq!(
            actions.last().and_then(|action| action.edge_id.as_deref()),
            Some("dom.stale_reuse.click")
        );
        let target = actions
            .last()
            .and_then(|action| action.target.as_ref())
            .unwrap();
        assert!(target.uses_cached_point());
        assert!(target.disables_fallback());
    }
}

pub fn mutate_action_sequence<R: Rng + ?Sized>(
    rng: &mut R,
    actions: &mut Vec<Action>,
    max_actions: usize,
    interactables: &[InteractableMetadata],
) -> bool {
    if rng.gen_range(0..100) < 40
        && insert_stale_reuse_suffix(rng, actions, max_actions, interactables)
    {
        return true;
    }

    if rng.gen_range(0..100) >= 15 {
        return interaction_fsa::mutate_action_sequence(rng, actions, max_actions, interactables);
    }

    let selectors = selectors_from_interactables(interactables);
    if actions.is_empty() {
        actions.push(random_action_from_metadata(rng, interactables, &selectors));
        return true;
    }

    match rng.gen_range(0..100) {
        0..=29 => {
            let idx = rng.gen_range(0..actions.len());
            mutate_action_params(rng, &mut actions[idx], interactables, &selectors);
            true
        }
        30..=59 => {
            if actions.len() < max_actions {
                let idx = rng.gen_range(0..=actions.len());
                actions.insert(
                    idx,
                    random_action_from_metadata(rng, interactables, &selectors),
                );
            } else {
                let idx = rng.gen_range(0..actions.len());
                actions[idx] = random_action_from_metadata(rng, interactables, &selectors);
            }
            true
        }
        60..=79 => {
            let idx = rng.gen_range(0..actions.len());
            actions[idx] = random_action_from_metadata(rng, interactables, &selectors);
            true
        }
        80..=89 if actions.len() > 1 => {
            let a = rng.gen_range(0..actions.len());
            let mut b = rng.gen_range(0..actions.len());
            if a == b {
                b = (b + 1) % actions.len();
            }
            actions.swap(a, b);
            true
        }
        _ if actions.len() > 1 => {
            let idx = rng.gen_range(0..actions.len());
            actions.remove(idx);
            true
        }
        _ => false,
    }
}

pub fn insert_stale_reuse_suffix<R: Rng + ?Sized>(
    rng: &mut R,
    actions: &mut Vec<Action>,
    max_actions: usize,
    interactables: &[InteractableMetadata],
) -> bool {
    let hazards: Vec<&InteractableMetadata> = interactables
        .iter()
        .filter(|item| item.is_lifecycle_hazard() && !item.selector.is_empty())
        .collect();
    if hazards.is_empty() || max_actions < 3 {
        return false;
    }

    let item = hazards[rng.gen_range(0..hazards.len())];
    let live_target = ActionTarget::dom(item.selector.clone());
    let stale_target = ActionTarget::dom_cached_point_no_fallback(item.selector.clone());
    let sleep_ms = if rng.gen_bool(0.6) { 16 } else { 50 };

    let mut suffix = Vec::new();
    if max_actions >= 4 {
        suffix.push(Action {
            kind: ActionKind::ScrollIntoView,
            edge_id: Some("dom.reveal.stale_reuse_target".to_string()),
            target: Some(live_target.clone()),
            to: None,
            text: None,
            key: None,
            x: None,
            y: None,
            millis: None,
        });
    }
    let trigger_kind = if item.is_focusable && rng.gen_bool(0.25) {
        ActionKind::Focus
    } else {
        ActionKind::Click
    };
    suffix.push(Action {
        kind: trigger_kind,
        edge_id: Some("dom.trigger.invalidation".to_string()),
        target: Some(live_target),
        to: None,
        text: None,
        key: None,
        x: None,
        y: None,
        millis: None,
    });
    suffix.push(Action {
        kind: ActionKind::Sleep,
        edge_id: Some("time.sleep.after_invalidation".to_string()),
        target: None,
        to: None,
        text: None,
        key: None,
        x: None,
        y: None,
        millis: Some(sleep_ms),
    });
    suffix.push(Action {
        kind: ActionKind::Click,
        edge_id: Some("dom.stale_reuse.click".to_string()),
        target: Some(stale_target),
        to: None,
        text: None,
        key: None,
        x: None,
        y: None,
        millis: None,
    });

    let keep = max_actions.saturating_sub(suffix.len());
    actions.truncate(keep);
    actions.extend(suffix);
    true
}

fn random_action_from_metadata<R: Rng + ?Sized>(
    rng: &mut R,
    interactables: &[InteractableMetadata],
    fallback_selectors: &[String],
) -> Action {
    if interactables.is_empty() {
        return random_generic_action(rng, fallback_selectors);
    }

    let mut weights = Vec::new();
    weights.extend(std::iter::repeat_n("click", 14));
    weights.extend(std::iter::repeat_n("hover", 6));
    weights.extend(std::iter::repeat_n("scroll", 5));
    weights.extend(std::iter::repeat_n("key", 4));

    if interactables.iter().any(|item| item.is_text_input) {
        weights.extend(std::iter::repeat_n("type", 12));
        weights.extend(std::iter::repeat_n("clear", 4));
    }
    if interactables
        .iter()
        .any(|item| item.is_focusable || item.has_handler)
    {
        weights.extend(std::iter::repeat_n("focus", 6));
    }
    if interactables.iter().any(|item| item.is_draggable)
        && interactables.iter().any(|item| item.is_drop_target)
    {
        weights.extend(std::iter::repeat_n("dragdrop", 12));
    }

    let (mut action, edge_id) = match weights[rng.gen_range(0..weights.len())] {
        "click" => (
            Action::click(preferred_target(rng, interactables, fallback_selectors)),
            "random.click",
        ),
        "hover" => (
            Action::hover(preferred_target(rng, interactables, fallback_selectors)),
            "random.hover",
        ),
        "type" => (
            Action::type_text(
                target_matching(rng, interactables, |item| item.is_text_input)
                    .unwrap_or_else(|| preferred_target(rng, interactables, fallback_selectors)),
                random_text(rng),
            ),
            "random.type",
        ),
        "clear" => (
            Action {
                kind: ActionKind::Clear,
                edge_id: None,
                target: Some(
                    target_matching(rng, interactables, |item| item.is_text_input).unwrap_or_else(
                        || preferred_target(rng, interactables, fallback_selectors),
                    ),
                ),
                to: None,
                text: None,
                key: None,
                x: None,
                y: None,
                millis: None,
            },
            "random.clear",
        ),
        "focus" => (
            Action::focus(
                target_matching(rng, interactables, |item| {
                    item.is_focusable || item.has_handler
                })
                .unwrap_or_else(|| preferred_target(rng, interactables, fallback_selectors)),
            ),
            "random.focus",
        ),
        "dragdrop" => (
            Action::drag_drop(
                target_matching(rng, interactables, |item| item.is_draggable)
                    .unwrap_or_else(|| preferred_target(rng, interactables, fallback_selectors)),
                target_matching(rng, interactables, |item| item.is_drop_target)
                    .unwrap_or_else(|| preferred_target(rng, interactables, fallback_selectors)),
            ),
            "random.dragdrop",
        ),
        "scroll" => (
            Action::scroll(
                rng.gen_range(-500_i64..=500_i64),
                rng.gen_range(-500_i64..=500_i64),
            ),
            "random.scroll",
        ),
        "key" => (Action::press_key(random_key(rng)), "random.key"),
        _ => (
            random_generic_action(rng, fallback_selectors),
            "random.fallback",
        ),
    };
    if action.edge_id.is_none() {
        action.edge_id = Some(edge_id.to_string());
    }
    action
}

fn random_generic_action<R: Rng + ?Sized>(rng: &mut R, selectors: &[String]) -> Action {
    let target = random_dom_target(rng, selectors);
    let mut action = match rng.gen_range(0..12) {
        0 => Action::click(target),
        1 => Action::hover(target),
        2 => Action::focus(target),
        3 => Action::type_text(target, random_text(rng)),
        4 => Action::scroll(
            rng.gen_range(-500_i64..=500_i64),
            rng.gen_range(-500_i64..=500_i64),
        ),
        5 => Action::press_key(random_key(rng)),
        6 => Action::sleep(rng.gen_range(10_u64..=200_u64)),
        _ => Action::click(target),
    };
    action.edge_id = Some("random.fallback".to_string());
    action
}

fn mutate_action_params<R: Rng + ?Sized>(
    rng: &mut R,
    action: &mut Action,
    interactables: &[InteractableMetadata],
    selectors: &[String],
) {
    match action.kind {
        ActionKind::Click
        | ActionKind::DoubleClick
        | ActionKind::RightClick
        | ActionKind::Clear
        | ActionKind::ScrollIntoView
        | ActionKind::Focus
        | ActionKind::Blur
        | ActionKind::Hover => {
            action.target = Some(preferred_target(rng, interactables, selectors));
        }
        ActionKind::TypeText => {
            if rng.gen_bool(0.5) {
                action.target = Some(preferred_target(rng, interactables, selectors));
            } else {
                action.text = Some(random_text(rng));
            }
        }
        ActionKind::DragDrop => {
            if rng.gen_bool(0.5) {
                action.target = Some(preferred_target(rng, interactables, selectors));
            } else {
                action.to = Some(preferred_target(rng, interactables, selectors));
            }
        }
        ActionKind::Scroll => {
            action.x = Some(action.x.unwrap_or(0) + rng.gen_range(-200_i64..=200_i64));
            action.y = Some(action.y.unwrap_or(0) + rng.gen_range(-200_i64..=200_i64));
        }
        ActionKind::PressKey => action.key = Some(random_key(rng)),
        ActionKind::Sleep => action.millis = Some(rng.gen_range(1_u64..=500_u64)),
        ActionKind::Refresh | ActionKind::Back | ActionKind::Forward => {
            *action = random_generic_action(rng, selectors);
        }
    }
}

fn preferred_target<R: Rng + ?Sized>(
    rng: &mut R,
    interactables: &[InteractableMetadata],
    fallback_selectors: &[String],
) -> ActionTarget {
    target_matching(rng, interactables, |item| item.has_handler)
        .or_else(|| target_matching(rng, interactables, |_| true))
        .unwrap_or_else(|| random_dom_target(rng, fallback_selectors))
}

fn target_matching<R, F>(
    rng: &mut R,
    interactables: &[InteractableMetadata],
    predicate: F,
) -> Option<ActionTarget>
where
    R: Rng + ?Sized,
    F: Fn(&InteractableMetadata) -> bool,
{
    let candidates: Vec<&InteractableMetadata> = interactables
        .iter()
        .filter(|item| predicate(item))
        .collect();
    if candidates.is_empty() {
        return None;
    }
    Some(ActionTarget::dom(
        candidates[rng.gen_range(0..candidates.len())]
            .selector
            .clone(),
    ))
}

fn random_dom_target<R: Rng + ?Sized>(rng: &mut R, selectors: &[String]) -> ActionTarget {
    if !selectors.is_empty() && rng.gen_range(0..100) < 80 {
        return ActionTarget::dom(selectors[rng.gen_range(0..selectors.len())].clone());
    }
    ActionTarget::dom(FALLBACK_SELECTORS[rng.gen_range(0..FALLBACK_SELECTORS.len())])
}

fn random_text<R: Rng + ?Sized>(rng: &mut R) -> String {
    TEXTS[rng.gen_range(0..TEXTS.len())].to_string()
}

fn random_key<R: Rng + ?Sized>(rng: &mut R) -> String {
    KEYS[rng.gen_range(0..KEYS.len())].to_string()
}
