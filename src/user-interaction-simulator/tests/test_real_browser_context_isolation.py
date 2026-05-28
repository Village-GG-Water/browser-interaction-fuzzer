import contextlib
import functools
import http.server
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from browser_env import BrowserSession, start_playwright  # noqa: E402


RUN_REAL_BROWSER = os.environ.get("RUN_REAL_BROWSER_CONTEXT_ISOLATION") == "1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dotenv_vars() -> dict[str, str]:
    env_path = _repo_root() / ".env"
    if not env_path.exists():
        return {}
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _browser_path() -> str | None:
    value = os.environ.get("BROWSER_PATH") or _dotenv_vars().get("BROWSER_PATH")
    if value and Path(value).exists():
        return value
    return None


@contextlib.contextmanager
def _http_origin(root: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", _free_port()), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_probe_site(root: Path) -> None:
    root.joinpath("writer.html").write_text(
        "<!doctype html><title>writer</title><button id='probe'>write</button>",
        encoding="utf-8",
    )
    root.joinpath("reader.html").write_text(
        "<!doctype html><title>reader</title><button id='probe'>read</button>",
        encoding="utf-8",
    )
    root.joinpath("sw.js").write_text(
        "self.addEventListener('fetch', () => {});",
        encoding="utf-8",
    )


def _config(tmp: Path, reuse_browser: bool) -> dict[str, object]:
    browser_path = _browser_path()
    if browser_path is None:
        raise unittest.SkipTest("BROWSER_PATH is not set or does not exist")
    return {
        "browser_kind": "chromium",
        "browser_path": browser_path,
        "sancov_dir": str(tmp / "sancov"),
        "asan_dir": str(tmp / "asan"),
        "out_dir": str(tmp / "out"),
        "iteration_timeout_ms": 30000,
        "disable_breakpad": True,
        "reuse_browser": reuse_browser,
    }


def _contaminate_context(page) -> None:
    page.evaluate(
        """async () => {
            localStorage.setItem("probe.local", "leak");
            sessionStorage.setItem("probe.session", "leak");
            document.cookie = "probe_cookie=leak; path=/; SameSite=Lax";
            window.name = "probe-window-name";
            globalThis.__probeGlobal = "leak";

            await new Promise((resolve, reject) => {
                const request = indexedDB.open("probe-db", 1);
                request.onupgradeneeded = () => {
                    request.result.createObjectStore("store");
                };
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const db = request.result;
                    const tx = db.transaction("store", "readwrite");
                    tx.objectStore("store").put("leak", "key");
                    tx.oncomplete = () => {
                        db.close();
                        resolve();
                    };
                    tx.onerror = () => reject(tx.error);
                };
            });

            if (window.caches) {
                const cache = await caches.open("probe-cache");
                await cache.put("/probe-cached", new Response("leak"));
            }
            if (navigator.serviceWorker) {
                await navigator.serviceWorker.register("/sw.js");
                await navigator.serviceWorker.ready;
            }
        }"""
    )


def _read_context_state(page) -> dict[str, object]:
    return page.evaluate(
        """async () => {
            let idbValue = null;
            let idbError = null;
            try {
                idbValue = await new Promise((resolve, reject) => {
                    const request = indexedDB.open("probe-db", 1);
                    request.onerror = () => reject(request.error);
                    request.onupgradeneeded = () => {
                        request.result.createObjectStore("store");
                    };
                    request.onsuccess = () => {
                        const db = request.result;
                        if (!db.objectStoreNames.contains("store")) {
                            db.close();
                            resolve(null);
                            return;
                        }
                        const tx = db.transaction("store", "readonly");
                        const getRequest = tx.objectStore("store").get("key");
                        getRequest.onsuccess = () => {
                            db.close();
                            resolve(getRequest.result ?? null);
                        };
                        getRequest.onerror = () => {
                            db.close();
                            reject(getRequest.error);
                        };
                    };
                });
            } catch (error) {
                idbError = String(error);
            }

            let cacheKeys = [];
            if (window.caches) {
                cacheKeys = await caches.keys();
            }
            let serviceWorkers = null;
            if (navigator.serviceWorker) {
                serviceWorkers = (await navigator.serviceWorker.getRegistrations()).length;
            }
            let geolocationPermission = null;
            if (navigator.permissions) {
                try {
                    geolocationPermission = (await navigator.permissions.query({name: "geolocation"})).state;
                } catch (_) {}
            }

            return {
                localStorageValue: localStorage.getItem("probe.local"),
                sessionStorageValue: sessionStorage.getItem("probe.session"),
                cookie: document.cookie,
                windowName: window.name,
                globalValue: globalThis.__probeGlobal ?? null,
                initScriptValue: globalThis.__probeInitScript ?? null,
                bindingType: typeof globalThis.probeBinding,
                idbValue,
                idbError,
                cacheKeys,
                serviceWorkers,
                geolocationPermission,
            };
        }"""
    )


class TestRealBrowserContextIsolation(unittest.TestCase):
    @unittest.skipUnless(RUN_REAL_BROWSER, "set RUN_REAL_BROWSER_CONTEXT_ISOLATION=1 to run")
    def test_context_state_does_not_leak_with_or_without_browser_reuse(self):
        results = {
            "no_reuse": self._run_probe(reuse_browser=False),
            "reuse": self._run_probe(reuse_browser=True),
        }

        for mode, result in results.items():
            with self.subTest(mode=mode):
                state = result["second_context_state"]
                self.assertIsNone(state["localStorageValue"], state)
                self.assertIsNone(state["sessionStorageValue"], state)
                self.assertNotIn("probe_cookie=leak", state["cookie"], state)
                self.assertEqual(state["windowName"], "", state)
                self.assertIsNone(state["globalValue"], state)
                self.assertIsNone(state["initScriptValue"], state)
                self.assertEqual(state["bindingType"], "undefined", state)
                self.assertIsNone(state["idbValue"], state)
                self.assertEqual(state["cacheKeys"], [], state)
                self.assertEqual(state["serviceWorkers"], 0, state)
                self.assertIn(state["geolocationPermission"], (None, "prompt"), state)
                self.assertEqual(result["open_contexts_after_first_close"], 0, result)
                self.assertEqual(result["open_contexts_after_second_close"], 0, result)

        self.assertNotEqual(
            results["no_reuse"]["first_browser_launch_id"],
            results["no_reuse"]["second_browser_launch_id"],
        )
        self.assertEqual(
            results["reuse"]["first_browser_launch_id"],
            results["reuse"]["second_browser_launch_id"],
        )
        self.assertTrue(results["reuse"]["second_browser_reused"])

    def _run_probe(self, reuse_browser: bool) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            site = tmp / "site"
            site.mkdir()
            _write_probe_site(site)
            config = _config(tmp, reuse_browser)

            with _http_origin(site) as origin:
                playwright = start_playwright()
                session = BrowserSession(playwright, config)
                try:
                    browser, context = session.open_context(tmp / "profile-1")
                    context.add_init_script("globalThis.__probeInitScript = 'leak';")
                    context.expose_binding("probeBinding", lambda source: "leak")
                    context.grant_permissions(["geolocation"], origin=origin)
                    page = context.new_page()
                    page.goto(f"{origin}/writer.html", timeout=30000, wait_until="load")
                    _contaminate_context(page)
                    first_open = dict(session.diagnostics())
                    session.close_context(browser, context, tmp / "profile-1")
                    first_close = dict(session.diagnostics())

                    browser, context = session.open_context(tmp / "profile-2")
                    page = context.new_page()
                    page.goto(f"{origin}/reader.html", timeout=30000, wait_until="load")
                    second_open = dict(session.diagnostics())
                    second_context_state = _read_context_state(page)
                    session.close_context(browser, context, tmp / "profile-2")
                    second_close = dict(session.diagnostics())
                finally:
                    session.close()
                    playwright.stop()

        return {
            "first_browser_launch_id": first_open["browser_launch_id"],
            "second_browser_launch_id": second_open["browser_launch_id"],
            "second_browser_reused": second_open["browser_reused"],
            "open_contexts_after_first_close": first_close["open_contexts_after_close"],
            "open_contexts_after_second_close": second_close["open_contexts_after_close"],
            "second_context_state": second_context_state,
        }


if __name__ == "__main__":
    unittest.main()
