use rand::Rng;

use super::action_ops::InteractableMetadata;
use crate::fuzzing_engine::actions::{Action, ActionKind, ActionTarget, validate_actions};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum InteractionState {
    PageReady,
    ElementPrimed,
    PointerOver,
    FocusedElement,
    TextFocused,
    AfterEvent,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InteractionCursor {
    pub state: InteractionState,
    pub target: Option<ActionTarget>,
}

impl InteractionCursor {
    fn page_ready() -> Self {
        Self {
            state: InteractionState::PageReady,
            target: None,
        }
    }

    fn at(state: InteractionState, target: Option<ActionTarget>) -> Self {
        Self { state, target }
    }
}

#[derive(Debug, Clone)]
struct WeightedEdge {
    action: Action,
    next: InteractionCursor,
    weight: u32,
}

pub fn generate_action_sequence<R: Rng + ?Sized>(
    rng: &mut R,
    max_len: usize,
    interactables: &[InteractableMetadata],
    _action_hints: &[Action],
) -> Vec<Action> {
    let max_len = max_len.max(1);
    let target_len = rng.gen_range(1..=max_len);
    extend_from_cursor(
        rng,
        Vec::with_capacity(target_len),
        target_len,
        interactables,
    )
}

pub fn mutate_action_sequence<R: Rng + ?Sized>(
    rng: &mut R,
    actions: &mut Vec<Action>,
    max_actions: usize,
    interactables: &[InteractableMetadata],
) -> bool {
    let max_actions = max_actions.max(1);
    let original = actions.clone();
    if actions.is_empty() {
        *actions = generate_action_sequence(rng, 1, interactables, &[]);
        return true;
    }

    actions.truncate(max_actions);
    let len = actions.len();
    let (repair_start, target_len) = match rng.gen_range(0..100) {
        0..=39 => (rng.gen_range(0..len), len),
        40..=69 if len < max_actions => (rng.gen_range(0..=len), len + 1),
        70..=84 if len > 1 => {
            let idx = rng.gen_range(0..len);
            actions.remove(idx);
            (idx.min(actions.len()), len - 1)
        }
        _ => (rng.gen_range(0..len), len),
    };

    let (prefix, _) = replay_prefix(&actions[..repair_start], interactables);
    *actions = extend_from_cursor(rng, prefix, target_len.max(1), interactables);
    if actions.len() <= max_actions && validate_actions(actions).is_ok() {
        true
    } else {
        *actions = original;
        false
    }
}

fn extend_from_cursor<R: Rng + ?Sized>(
    rng: &mut R,
    mut actions: Vec<Action>,
    target_len: usize,
    interactables: &[InteractableMetadata],
) -> Vec<Action> {
    let mut cursor = replay_prefix(&actions, interactables).1;
    while actions.len() < target_len {
        let candidates = materialize_edges(rng, &cursor, interactables);
        let Some(edge) = choose_edge(rng, &candidates) else {
            break;
        };
        cursor = edge.next.clone();
        actions.push(edge.action.clone());
    }
    actions
}

fn replay_prefix(
    actions: &[Action],
    interactables: &[InteractableMetadata],
) -> (Vec<Action>, InteractionCursor) {
    let mut cursor = InteractionCursor::page_ready();
    let mut prefix = Vec::with_capacity(actions.len());
    for action in actions {
        let Some(next) = replay_action(&cursor, action, interactables) else {
            break;
        };
        prefix.push(action.clone());
        cursor = next;
    }
    (prefix, cursor)
}

fn materialize_edges<R: Rng + ?Sized>(
    rng: &mut R,
    cursor: &InteractionCursor,
    interactables: &[InteractableMetadata],
) -> Vec<WeightedEdge> {
    let mut edges = Vec::new();
    match cursor.state {
        InteractionState::PageReady => {
            push_scroll(
                &mut edges,
                "dom.scroll.window",
                InteractionState::PageReady,
                6,
            );
            push_sleep(
                &mut edges,
                "time.sleep.idle",
                InteractionState::PageReady,
                1,
            );
            if let Some(item) = pick_any(rng, interactables) {
                push_reveal(&mut edges, item, 5);
            }
            push_hover_edges(rng, &mut edges, interactables, None, 5);
            push_click_edges(rng, &mut edges, interactables, None, 10);
            push_focus_edges(rng, &mut edges, interactables, None, 6);
            push_dragdrop_edges(rng, &mut edges, interactables, 8);
        }
        InteractionState::ElementPrimed => {
            push_hover_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 7);
            push_click_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 10);
            push_focus_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 6);
        }
        InteractionState::PointerOver => {
            push_click_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 12);
            push_pointer_context_edges(&mut edges, cursor.target.clone());
            push_focus_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 5);
        }
        InteractionState::FocusedElement => {
            push_key(
                &mut edges,
                "dom.key.focused",
                InteractionState::FocusedElement,
                cursor.target.clone(),
                9,
            );
            push_blur(&mut edges, cursor.target.clone(), 5);
            push_click_edges(rng, &mut edges, interactables, cursor.target.as_ref(), 4);
        }
        InteractionState::TextFocused => {
            push_type(&mut edges, cursor.target.clone(), 14);
            push_clear(&mut edges, cursor.target.clone(), 5);
            push_key(
                &mut edges,
                "dom.key.text_focused",
                InteractionState::TextFocused,
                cursor.target.clone(),
                7,
            );
            push_blur(&mut edges, cursor.target.clone(), 5);
        }
        InteractionState::AfterEvent => {
            push_sleep(
                &mut edges,
                "time.sleep.after_event",
                InteractionState::PageReady,
                8,
            );
            push_scroll(
                &mut edges,
                "dom.scroll.after_event",
                InteractionState::PageReady,
                4,
            );
            push_click_edges(rng, &mut edges, interactables, None, 5);
            push_focus_edges(rng, &mut edges, interactables, None, 3);
        }
    }
    if edges.is_empty() {
        push_scroll(
            &mut edges,
            "dom.scroll.repair",
            InteractionState::PageReady,
            1,
        );
    }
    edges
}

fn choose_edge<'a, R: Rng + ?Sized>(
    rng: &mut R,
    edges: &'a [WeightedEdge],
) -> Option<&'a WeightedEdge> {
    if edges.is_empty() {
        return None;
    }
    let total: u32 = edges.iter().map(|edge| edge.weight).sum();
    let mut pick = rng.gen_range(0..total);
    for edge in edges {
        if pick < edge.weight {
            return Some(edge);
        }
        pick -= edge.weight;
    }
    edges.last()
}

fn push_scroll(
    edges: &mut Vec<WeightedEdge>,
    edge_id: &'static str,
    next: InteractionState,
    weight: u32,
) {
    let mut action = Action::scroll(0, 300);
    action.edge_id = Some(edge_id.to_string());
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(next, None),
        weight,
    });
}

fn push_sleep(
    edges: &mut Vec<WeightedEdge>,
    edge_id: &'static str,
    next: InteractionState,
    weight: u32,
) {
    let mut action = Action::sleep(50);
    action.edge_id = Some(edge_id.to_string());
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(next, None),
        weight,
    });
}

fn push_reveal(edges: &mut Vec<WeightedEdge>, item: &InteractableMetadata, weight: u32) {
    let target = ActionTarget::dom(item.selector.clone());
    let action = Action {
        kind: ActionKind::ScrollIntoView,
        edge_id: Some("dom.reveal.target".to_string()),
        target: Some(target.clone()),
        to: None,
        text: None,
        key: None,
        x: None,
        y: None,
        millis: None,
    };
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(InteractionState::ElementPrimed, Some(target)),
        weight,
    });
}

fn push_hover_edges<R: Rng + ?Sized>(
    rng: &mut R,
    edges: &mut Vec<WeightedEdge>,
    interactables: &[InteractableMetadata],
    preferred: Option<&ActionTarget>,
    base_weight: u32,
) {
    for item in matching_items(rng, interactables, preferred, |_| true)
        .into_iter()
        .take(2)
    {
        let target = ActionTarget::dom(item.selector.clone());
        let event_weight = if event_matches(item, &["mouseover", "mouseenter", "pointerover"]) {
            base_weight + 5
        } else {
            base_weight
        };
        let mut action = Action::hover(target.clone());
        action.edge_id = Some(
            if event_weight > base_weight {
                "dom.hover.event"
            } else {
                "dom.hover.target"
            }
            .to_string(),
        );
        edges.push(WeightedEdge {
            action,
            next: next_after_event_action(item, InteractionState::PointerOver, Some(target)),
            weight: event_weight,
        });
    }
}

fn push_click_edges<R: Rng + ?Sized>(
    rng: &mut R,
    edges: &mut Vec<WeightedEdge>,
    interactables: &[InteractableMetadata],
    preferred: Option<&ActionTarget>,
    base_weight: u32,
) {
    for item in matching_items(rng, interactables, preferred, |_| true)
        .into_iter()
        .take(2)
    {
        let target = ActionTarget::dom(item.selector.clone());
        let event_click = event_matches(
            item,
            &[
                "click",
                "mousedown",
                "mouseup",
                "pointerdown",
                "pointerup",
                "contextmenu",
            ],
        ) || item.has_handler;
        let mut action = Action::click(target.clone());
        action.edge_id = Some(
            if event_click {
                "dom.click.event"
            } else {
                "dom.click.target"
            }
            .to_string(),
        );
        edges.push(WeightedEdge {
            action,
            next: next_after_click(item, target),
            weight: if event_click {
                base_weight + 8
            } else {
                base_weight
            },
        });
    }
}

fn push_pointer_context_edges(edges: &mut Vec<WeightedEdge>, target: Option<ActionTarget>) {
    let Some(target) = target else {
        return;
    };
    for (kind, edge_id, weight) in [
        (ActionKind::DoubleClick, "dom.double_click.pointer_over", 3),
        (ActionKind::RightClick, "dom.right_click.pointer_over", 3),
    ] {
        edges.push(WeightedEdge {
            action: Action {
                kind,
                edge_id: Some(edge_id.to_string()),
                target: Some(target.clone()),
                to: None,
                text: None,
                key: None,
                x: None,
                y: None,
                millis: None,
            },
            next: InteractionCursor::at(InteractionState::AfterEvent, Some(target.clone())),
            weight,
        });
    }
}

fn push_focus_edges<R: Rng + ?Sized>(
    rng: &mut R,
    edges: &mut Vec<WeightedEdge>,
    interactables: &[InteractableMetadata],
    preferred: Option<&ActionTarget>,
    base_weight: u32,
) {
    for item in matching_items(rng, interactables, preferred, |item| {
        item.is_focusable || item.is_text_input || item.has_handler
    })
    .into_iter()
    .take(2)
    {
        let target = ActionTarget::dom(item.selector.clone());
        let mut action = Action::focus(target.clone());
        action.edge_id = Some(
            if item.is_text_input {
                "dom.focus.text_input"
            } else if event_matches(item, &["focus"]) || item.has_handler {
                "dom.focus.event"
            } else {
                "dom.focus.target"
            }
            .to_string(),
        );
        let next = if item.is_text_input {
            InteractionState::TextFocused
        } else if event_matches(item, &["focus"]) || item.has_handler {
            InteractionState::AfterEvent
        } else {
            InteractionState::FocusedElement
        };
        edges.push(WeightedEdge {
            action,
            next: InteractionCursor::at(next, Some(target)),
            weight: if item.is_text_input {
                base_weight + 7
            } else {
                base_weight
            },
        });
    }
}

fn push_dragdrop_edges<R: Rng + ?Sized>(
    rng: &mut R,
    edges: &mut Vec<WeightedEdge>,
    interactables: &[InteractableMetadata],
    weight: u32,
) {
    let Some(source) = pick_matching(rng, interactables, |item| item.is_draggable) else {
        return;
    };
    let Some(dest) = pick_matching(rng, interactables, |item| item.is_drop_target) else {
        return;
    };
    let mut action = Action::drag_drop(
        ActionTarget::dom(source.selector.clone()),
        ActionTarget::dom(dest.selector.clone()),
    );
    action.edge_id = Some("dom.dragdrop.pair".to_string());
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(InteractionState::AfterEvent, None),
        weight,
    });
}

fn push_type(edges: &mut Vec<WeightedEdge>, target: Option<ActionTarget>, weight: u32) {
    let Some(target) = target else {
        return;
    };
    let mut action = Action::type_text(target.clone(), "fuzz");
    action.edge_id = Some("dom.type.focused_text".to_string());
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(InteractionState::TextFocused, Some(target)),
        weight,
    });
}

fn push_clear(edges: &mut Vec<WeightedEdge>, target: Option<ActionTarget>, weight: u32) {
    let Some(target) = target else {
        return;
    };
    edges.push(WeightedEdge {
        action: Action {
            kind: ActionKind::Clear,
            edge_id: Some("dom.clear.focused_text".to_string()),
            target: Some(target.clone()),
            to: None,
            text: None,
            key: None,
            x: None,
            y: None,
            millis: None,
        },
        next: InteractionCursor::at(InteractionState::TextFocused, Some(target)),
        weight,
    });
}

fn push_key(
    edges: &mut Vec<WeightedEdge>,
    edge_id: &'static str,
    next: InteractionState,
    target: Option<ActionTarget>,
    weight: u32,
) {
    let mut action = Action::press_key("Enter");
    action.edge_id = Some(edge_id.to_string());
    edges.push(WeightedEdge {
        action,
        next: InteractionCursor::at(next, target),
        weight,
    });
}

fn push_blur(edges: &mut Vec<WeightedEdge>, target: Option<ActionTarget>, weight: u32) {
    let Some(target) = target else {
        return;
    };
    edges.push(WeightedEdge {
        action: Action {
            kind: ActionKind::Blur,
            edge_id: Some("dom.blur.focused".to_string()),
            target: Some(target),
            to: None,
            text: None,
            key: None,
            x: None,
            y: None,
            millis: None,
        },
        next: InteractionCursor::page_ready(),
        weight,
    });
}

fn next_after_click(item: &InteractableMetadata, target: ActionTarget) -> InteractionCursor {
    if event_matches(
        item,
        &[
            "click",
            "mousedown",
            "mouseup",
            "pointerdown",
            "pointerup",
            "contextmenu",
        ],
    ) || item.has_handler
    {
        return InteractionCursor::at(InteractionState::AfterEvent, Some(target));
    }
    if item.is_text_input {
        return InteractionCursor::at(InteractionState::TextFocused, Some(target));
    }
    if item.is_focusable {
        return InteractionCursor::at(InteractionState::FocusedElement, Some(target));
    }
    InteractionCursor::page_ready()
}

fn next_after_event_action(
    item: &InteractableMetadata,
    fallback: InteractionState,
    target: Option<ActionTarget>,
) -> InteractionCursor {
    if item.has_handler {
        InteractionCursor::at(InteractionState::AfterEvent, target)
    } else {
        InteractionCursor::at(fallback, target)
    }
}

fn replay_action(
    cursor: &InteractionCursor,
    action: &Action,
    interactables: &[InteractableMetadata],
) -> Option<InteractionCursor> {
    let item = action
        .target
        .as_ref()
        .and_then(|target| item_for_target(target, interactables));
    match action.kind {
        ActionKind::Scroll | ActionKind::Sleep => Some(InteractionCursor::page_ready()),
        ActionKind::ScrollIntoView => action
            .target
            .clone()
            .map(|target| InteractionCursor::at(InteractionState::ElementPrimed, Some(target))),
        ActionKind::Hover => {
            if !matches!(
                cursor.state,
                InteractionState::PageReady | InteractionState::ElementPrimed
            ) {
                return None;
            }
            action.target.clone().map(|target| {
                let fallback = InteractionState::PointerOver;
                item.map_or_else(
                    || InteractionCursor::at(fallback, Some(target.clone())),
                    |item| next_after_event_action(item, fallback, Some(target.clone())),
                )
            })
        }
        ActionKind::Click | ActionKind::DoubleClick | ActionKind::RightClick => {
            action.target.clone().map(|target| {
                item.map_or_else(
                    || InteractionCursor::at(InteractionState::AfterEvent, Some(target.clone())),
                    |item| next_after_click(item, target.clone()),
                )
            })
        }
        ActionKind::Focus => action.target.clone().map(|target| {
            if let Some(item) = item {
                if item.is_text_input {
                    return InteractionCursor::at(InteractionState::TextFocused, Some(target));
                }
                if event_matches(item, &["focus"]) || item.has_handler {
                    return InteractionCursor::at(InteractionState::AfterEvent, Some(target));
                }
            }
            InteractionCursor::at(InteractionState::FocusedElement, Some(target))
        }),
        ActionKind::TypeText | ActionKind::Clear => {
            if cursor.state != InteractionState::TextFocused {
                return None;
            }
            action
                .target
                .clone()
                .map(|target| InteractionCursor::at(InteractionState::TextFocused, Some(target)))
        }
        ActionKind::PressKey => {
            if matches!(
                cursor.state,
                InteractionState::FocusedElement | InteractionState::TextFocused
            ) {
                Some(cursor.clone())
            } else {
                None
            }
        }
        ActionKind::Blur => Some(InteractionCursor::page_ready()),
        ActionKind::DragDrop => Some(InteractionCursor::at(InteractionState::AfterEvent, None)),
        ActionKind::Refresh | ActionKind::Back | ActionKind::Forward => None,
    }
}

fn matching_items<'a, R, F>(
    rng: &mut R,
    interactables: &'a [InteractableMetadata],
    preferred: Option<&ActionTarget>,
    predicate: F,
) -> Vec<&'a InteractableMetadata>
where
    R: Rng + ?Sized,
    F: Fn(&InteractableMetadata) -> bool,
{
    if let Some(preferred) = preferred {
        if let Some(item) = item_for_target(preferred, interactables) {
            if predicate(item) {
                return vec![item];
            }
        }
    }
    let mut matches: Vec<&InteractableMetadata> = interactables
        .iter()
        .filter(|item| predicate(item))
        .collect();
    for i in 0..matches.len() {
        let j = rng.gen_range(i..matches.len());
        matches.swap(i, j);
    }
    matches
}

fn pick_any<'a, R: Rng + ?Sized>(
    rng: &mut R,
    interactables: &'a [InteractableMetadata],
) -> Option<&'a InteractableMetadata> {
    if interactables.is_empty() {
        None
    } else {
        Some(&interactables[rng.gen_range(0..interactables.len())])
    }
}

fn pick_matching<'a, R, F>(
    rng: &mut R,
    interactables: &'a [InteractableMetadata],
    predicate: F,
) -> Option<&'a InteractableMetadata>
where
    R: Rng + ?Sized,
    F: Fn(&InteractableMetadata) -> bool,
{
    let matches: Vec<&InteractableMetadata> = interactables
        .iter()
        .filter(|item| predicate(item))
        .collect();
    if matches.is_empty() {
        None
    } else {
        Some(matches[rng.gen_range(0..matches.len())])
    }
}

fn item_for_target<'a>(
    target: &ActionTarget,
    interactables: &'a [InteractableMetadata],
) -> Option<&'a InteractableMetadata> {
    let ActionTarget::Dom { selector } = target else {
        return None;
    };
    interactables.iter().find(|item| item.selector == *selector)
}

fn event_matches(item: &InteractableMetadata, events: &[&str]) -> bool {
    item.events
        .iter()
        .any(|event| events.contains(&event.as_str()))
}

#[cfg(test)]
mod tests {
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    use super::*;

    fn text_input() -> InteractableMetadata {
        InteractableMetadata {
            selector: "#name".to_string(),
            tag: "input".to_string(),
            events: vec!["input".to_string(), "focus".to_string()],
            is_text_input: true,
            is_draggable: false,
            is_drop_target: false,
            is_focusable: true,
            has_handler: true,
        }
    }

    fn button() -> InteractableMetadata {
        InteractableMetadata {
            selector: "#go".to_string(),
            tag: "button".to_string(),
            events: vec!["click".to_string()],
            is_text_input: false,
            is_draggable: false,
            is_drop_target: false,
            is_focusable: true,
            has_handler: true,
        }
    }

    #[test]
    fn generated_sequences_validate_and_stay_within_budget() {
        let mut rng = StdRng::seed_from_u64(4);
        for _ in 0..64 {
            let actions = generate_action_sequence(&mut rng, 3, &[text_input(), button()], &[]);
            assert!((1..=3).contains(&actions.len()));
            validate_actions(&actions).unwrap();
            assert!(actions.iter().all(|action| action.edge_id.is_some()));
        }
    }

    #[test]
    fn text_actions_require_text_focus_prefix() {
        let mut rng = StdRng::seed_from_u64(10);
        for _ in 0..128 {
            let actions = generate_action_sequence(&mut rng, 6, &[text_input()], &[]);
            for (idx, action) in actions.iter().enumerate() {
                if matches!(action.kind, ActionKind::TypeText | ActionKind::Clear) {
                    assert!(
                        actions[..idx]
                            .iter()
                            .any(|prefix| prefix.edge_id.as_deref() == Some("dom.focus.text_input")
                                || matches!(prefix.kind, ActionKind::Click)
                                    && matches!(prefix.target, Some(ActionTarget::Dom { ref selector }) if selector == "#name"))
                    );
                }
            }
        }
    }

    #[test]
    fn key_actions_require_focus_state() {
        let mut rng = StdRng::seed_from_u64(17);
        for _ in 0..128 {
            let actions = generate_action_sequence(&mut rng, 6, &[button()], &[]);
            for (idx, action) in actions.iter().enumerate() {
                if action.kind == ActionKind::PressKey {
                    assert!(actions[..idx].iter().any(|prefix| prefix.edge_id.as_deref()
                        == Some("dom.focus.target")
                        || prefix.edge_id.as_deref() == Some("dom.focus.event")));
                }
            }
        }
    }

    #[test]
    fn handler_click_can_enter_after_event() {
        let mut rng = StdRng::seed_from_u64(3);
        let edges = materialize_edges(&mut rng, &InteractionCursor::page_ready(), &[button()]);

        assert!(edges.iter().any(|edge| {
            edge.action.edge_id.as_deref() == Some("dom.click.event")
                && edge.next.state == InteractionState::AfterEvent
        }));
    }

    #[test]
    fn mutation_repairs_suffix_and_preserves_budget() {
        let mut rng = StdRng::seed_from_u64(9);
        let mut actions = vec![
            Action::scroll(0, 1),
            Action::type_text(ActionTarget::dom("#name"), "legacy"),
            Action::press_key("Enter"),
        ];

        for _ in 0..32 {
            mutate_action_sequence(&mut rng, &mut actions, 4, &[text_input(), button()]);
            assert!(!actions.is_empty());
            assert!(actions.len() <= 4);
            validate_actions(&actions).unwrap();
        }
    }
}
