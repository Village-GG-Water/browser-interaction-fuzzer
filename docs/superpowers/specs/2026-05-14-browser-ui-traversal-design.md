# Design: Atspi Node Traversal and Action Execution

## Purpose
Implement the logic to find UI elements (excluding DOM nodes) in browser applications (Chrome/Chromium) using AT-SPI and execute actions (click/focus) on them.

## Architecture
The logic will be integrated into the `BrowserUIBackend` class in `src/user-interaction-simulator/user_interaction_simulator/browser_ui.py`.

### Components
1. `_refresh_app`: Identifies the browser application instance from the AT-SPI desktop.
2. `_find_node_dfs`: Performs a depth-first search to find a node with a specific role and name, skipping DOM-related nodes to optimize performance.
3. `execute`: Main entry point that handles retries and coordination between application discovery and node searching.
4. `_perform_action`: Executes the requested action (click or focus) on the found element using AT-SPI interfaces (`Action` or `Component`).

## Data Flow
1. `execute` is called with action kind, role, and element name.
2. It enters a retry loop until timeout.
3. In each iteration:
   - `_refresh_app` finds the browser process.
   - For each window in the app, `_find_node_dfs` searches for the target element.
   - If found, `_perform_action` is executed and its result returned.
4. If timeout is reached, return `False`.

## Error Handling
- Use `try-except` blocks around AT-SPI calls to handle potential stability issues or transient errors during UI tree traversal.
- Return `False` if any step fails.

## Testing
- Verify syntax with `python3 -m py_compile`.
- (Manual/Integration) This logic requires a running X11/Wayland session with AT-SPI enabled and a browser open. In this headless environment, we'll focus on structural correctness and basic property checks if possible.
