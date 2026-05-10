use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionKind {
    Click,
    DoubleClick,
    RightClick,
    TypeText,
    Clear,
    DragDrop,
    Scroll,
    ScrollIntoView,
    Focus,
    Blur,
    Hover,
    PressKey,
    Refresh,
    Back,
    Forward,
    Sleep,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "space", rename_all = "snake_case")]
pub enum ActionTarget {
    Dom { selector: String },
    BrowserUi { role: String, name: String },
}

impl ActionTarget {
    pub fn dom(selector: impl Into<String>) -> Self {
        Self::Dom {
            selector: selector.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Action {
    pub kind: ActionKind,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<ActionTarget>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to: Option<ActionTarget>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub x: Option<i64>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub y: Option<i64>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub millis: Option<u64>,
}

impl Action {
    pub fn click(target: ActionTarget) -> Self {
        Self::with_target(ActionKind::Click, target)
    }

    pub fn hover(target: ActionTarget) -> Self {
        Self::with_target(ActionKind::Hover, target)
    }

    pub fn focus(target: ActionTarget) -> Self {
        Self::with_target(ActionKind::Focus, target)
    }

    pub fn type_text(target: ActionTarget, text: impl Into<String>) -> Self {
        Self {
            kind: ActionKind::TypeText,
            target: Some(target),
            text: Some(text.into()),
            ..Self::empty(ActionKind::TypeText)
        }
    }

    pub fn drag_drop(from: ActionTarget, to: ActionTarget) -> Self {
        Self {
            kind: ActionKind::DragDrop,
            target: Some(from),
            to: Some(to),
            ..Self::empty(ActionKind::DragDrop)
        }
    }

    pub fn scroll(x: i64, y: i64) -> Self {
        Self {
            kind: ActionKind::Scroll,
            x: Some(x),
            y: Some(y),
            ..Self::empty(ActionKind::Scroll)
        }
    }

    pub fn press_key(key: impl Into<String>) -> Self {
        Self {
            kind: ActionKind::PressKey,
            key: Some(key.into()),
            ..Self::empty(ActionKind::PressKey)
        }
    }

    pub fn sleep(millis: u64) -> Self {
        Self {
            kind: ActionKind::Sleep,
            millis: Some(millis),
            ..Self::empty(ActionKind::Sleep)
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        match self.kind {
            ActionKind::Click
            | ActionKind::DoubleClick
            | ActionKind::RightClick
            | ActionKind::Clear
            | ActionKind::ScrollIntoView
            | ActionKind::Focus
            | ActionKind::Blur
            | ActionKind::Hover => {
                require_target(self)?;
            }
            ActionKind::TypeText => {
                require_target(self)?;
                if self.text.is_none() {
                    return Err("type_text requires text".to_string());
                }
            }
            ActionKind::DragDrop => {
                require_target(self)?;
                if self.to.is_none() {
                    return Err("drag_drop requires destination target".to_string());
                }
            }
            ActionKind::Scroll => {
                if self.x.is_none() || self.y.is_none() {
                    return Err("scroll requires x and y".to_string());
                }
            }
            ActionKind::PressKey => {
                if self.key.is_none() {
                    return Err("press_key requires key".to_string());
                }
            }
            ActionKind::Sleep => {
                if self.millis.is_none() {
                    return Err("sleep requires millis".to_string());
                }
            }
            ActionKind::Refresh | ActionKind::Back | ActionKind::Forward => {}
        }
        Ok(())
    }

    fn with_target(kind: ActionKind, target: ActionTarget) -> Self {
        Self {
            kind,
            target: Some(target),
            ..Self::empty(kind)
        }
    }

    fn empty(kind: ActionKind) -> Self {
        Self {
            kind,
            target: None,
            to: None,
            text: None,
            key: None,
            x: None,
            y: None,
            millis: None,
        }
    }
}

fn require_target(action: &Action) -> Result<(), String> {
    if action.target.is_none() {
        return Err(format!("{:?} requires target", action.kind));
    }
    Ok(())
}

pub fn validate_actions(actions: &[Action]) -> Result<(), String> {
    for (idx, action) in actions.iter().enumerate() {
        action
            .validate()
            .map_err(|message| format!("invalid action at index {idx}: {message}"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Action, ActionKind, ActionTarget};

    #[test]
    fn serializes_dom_action_wire_shape() {
        let action = Action::click(ActionTarget::dom("#x1"));
        let json = serde_json::to_value(action).unwrap();

        assert_eq!(json["kind"], "click");
        assert_eq!(json["target"]["space"], "dom");
        assert_eq!(json["target"]["selector"], "#x1");
    }

    #[test]
    fn validates_required_fields() {
        let action = Action {
            kind: ActionKind::TypeText,
            target: Some(ActionTarget::dom("#x1")),
            text: None,
            to: None,
            key: None,
            x: None,
            y: None,
            millis: None,
        };

        assert!(action.validate().is_err());
    }
}
