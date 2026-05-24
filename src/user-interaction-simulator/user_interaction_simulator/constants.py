# src/user-interaction-simulator/user_interaction_simulator/constants.py

INTERACTABLE_CSS = (
    "a,button,input,textarea,select,details,summary,dialog,"
    "iframe,canvas,video,audio,[contenteditable],[tabindex],[draggable]"
)
TEXT_INPUTS_CSS = "input,textarea,select,[contenteditable]"
DRAGGABLE_CSS = "[draggable],img,a,div,canvas"
EVENT_HANDLER_CSS = (
    "[onclick],[ondblclick],[onmousedown],[onmouseup],"
    "[onfocus],[onblur],[oninput],[onchange],"
    "[onkeydown],[onkeyup],[onsubmit],"
    "[onpointerdown],[onpointerup],[ontouchstart],"
    "[onmouseover],[onmouseout],[oncontextmenu],"
    "[ondragstart],[ondrop]"
)

CRASH_MARKERS = [
    "crashed",
    "target closed",
    "browser closed",
    "connection refused",
    "browser has been closed",
    "process exited",
    "browser was disconnected",
]

CLEANUP_JS = """() => {
    try { localStorage.clear(); } catch (_) {}
    try { sessionStorage.clear(); } catch (_) {}
    try {
        if (navigator.serviceWorker) {
            navigator.serviceWorker.getRegistrations().then((regs) => {
                for (const reg of regs) { reg.unregister(); }
            });
        }
    } catch (_) {}
    try {
        if (window.caches && caches.keys) {
            caches.keys().then((keys) => {
                for (const k of keys) { caches.delete(k); }
            });
        }
    } catch (_) {}
}"""