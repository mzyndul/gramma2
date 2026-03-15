import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


def _debug_teardown(message):
    if os.environ.get("GRAMMA2_DEBUG_TEARDOWN"):
        print(message, flush=True)


def force_close_persistent_context(context, playwright, user_data_dir, *, grace_seconds=2.0):
    """Best-effort shutdown for persistent Chromium contexts with extensions."""
    browser_flag = f"--user-data-dir={user_data_dir}"
    _debug_teardown(f"browser_context teardown: collect pids for {browser_flag}")
    target_pids = _collect_target_pids(playwright, browser_flag)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        target_pids |= _collect_target_pids(playwright, browser_flag)
        if target_pids:
            break
        time.sleep(0.1)

    remaining = _live_pids(target_pids)
    if remaining:
        _debug_teardown(f"browser_context teardown: SIGTERM {sorted(remaining)}")
        _signal_pids(remaining, signal.SIGTERM)
        _wait_for_exit(remaining, timeout=1.0)

    remaining = _live_pids(target_pids)
    if remaining:
        _debug_teardown(f"browser_context teardown: SIGKILL {sorted(remaining)}")
        _signal_pids(remaining, signal.SIGKILL)
        _wait_for_exit(remaining, timeout=1.0)

    _debug_teardown("browser_context teardown: removing user data dir")
    shutil.rmtree(user_data_dir, ignore_errors=True)
    _debug_teardown("browser_context teardown: done")


def _collect_target_pids(playwright, browser_flag):
    targets = set()
    process_table = _process_table()
    driver_pid = _playwright_driver_pid(playwright)

    if driver_pid:
        targets.add(driver_pid)
        targets.update(_descendant_pids(driver_pid, process_table))

    for pid in _pids_with_arg(browser_flag, process_table):
        targets.add(pid)
        targets.update(_descendant_pids(pid, process_table))

    return targets


def _playwright_driver_pid(playwright):
    try:
        return playwright._impl_obj._connection._transport._proc.pid
    except Exception:
        return None


def _process_table():
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "pid=,ppid=,args="],
            text=True,
        )
    except Exception:
        return []

    rows = []
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        rows.append((pid, ppid, parts[2]))
    return rows


def _descendant_pids(root_pid, process_table):
    children_by_parent = {}
    for pid, ppid, _args in process_table:
        children_by_parent.setdefault(ppid, []).append(pid)

    descendants = set()
    queue = [root_pid]
    while queue:
        parent_pid = queue.pop()
        for child_pid in children_by_parent.get(parent_pid, ()):
            if child_pid in descendants:
                continue
            descendants.add(child_pid)
            queue.append(child_pid)
    return descendants


def _pids_with_arg(arg_fragment, process_table):
    return {
        pid
        for pid, _ppid, args in process_table
        if arg_fragment in args
    }


def _live_pids(pids):
    live = set()
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            live.add(pid)
        else:
            live.add(pid)
    return live


def _signal_pids(pids, sig):
    for pid in sorted(pids, reverse=True):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue


def _wait_for_exit(pids, *, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _live_pids(pids):
            return True
        time.sleep(0.1)
    return not _live_pids(pids)


# ---------------------------------------------------------------------------
# Mock grammar server on port 8555 (deterministic, no real LLM)
# ---------------------------------------------------------------------------

class _MockGrammarHandler(SimpleHTTPRequestHandler):
    # Sentences that the mock will return unchanged (for testing 0-change and partial-change)
    UNCHANGED_PREFIXES = ("This sentence is perfect",)

    # Class-level delay for /improve requests (ms). Set by fixtures for timing tests.
    _improve_delay_ms = 0

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _improve_suggestion(self, text):
        """Generate a suggestion for the given text. Unchanged prefixes return text as-is."""
        if any(text.startswith(p) for p in self.UNCHANGED_PREFIXES):
            return text
        return f"Fixed: {text}"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        if self.path == "/improve":
            if self._improve_delay_ms > 0:
                time.sleep(self._improve_delay_ms / 1000)
            text = data.get("text", "")
            suggestion = self._improve_suggestion(text)
            body = json.dumps({"suggestions": [suggestion]})
        elif self.path == "/improve-batch":
            sentences = data.get("sentences", [])
            results = []
            for s in sentences:
                results.append({
                    "original": s,
                    "suggestion": self._improve_suggestion(s),
                })
            body = json.dumps({"results": results})
        else:
            self.send_response(404)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())
            return

        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass  # silence request logs during tests


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


@pytest.fixture(scope="session")
def mock_server():
    server = _ReusableHTTPServer(("127.0.0.1", 8555), _MockGrammarHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    _debug_teardown("mock_server teardown: shutdown start")
    server.shutdown()
    server.server_close()
    _debug_teardown("mock_server teardown: shutdown done")


# ---------------------------------------------------------------------------
# Static file server for test_page.html
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_page_server():
    tests_dir = str(Path(__file__).parent)

    class _Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=tests_dir, **kwargs)

        def log_message(self, format, *args):
            pass

    # Pick a random available port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/test_page.html"
    _debug_teardown("test_page_server teardown: shutdown start")
    server.shutdown()
    server.server_close()
    _debug_teardown("test_page_server teardown: shutdown done")


# ---------------------------------------------------------------------------
# Playwright browser context with the extension loaded
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_context(mock_server):
    ext_path = str(Path(__file__).parent.parent / "extension")
    user_data_dir = tempfile.mkdtemp(prefix="gramma2-test-")

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        handle_sigint=False,
        handle_sigterm=False,
        handle_sighup=False,
        args=[
            f"--disable-extensions-except={ext_path}",
            f"--load-extension={ext_path}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    yield context
    _debug_teardown("browser_context teardown: start")
    force_close_persistent_context(context, pw, user_data_dir)


# ---------------------------------------------------------------------------
# Fresh page per test
# ---------------------------------------------------------------------------

@pytest.fixture
def page(test_page_server, browser_context):
    from playwright.sync_api import expect

    page = browser_context.new_page()
    page.set_default_timeout(5000)  # fail fast — 5s instead of 30s
    page.goto(test_page_server)
    expect(page.locator(".gramma2-icon")).to_be_hidden(timeout=5000)
    yield page
    page.close()


@pytest.fixture
def slow_improve():
    """Make /improve responses slow for testing progressive waiting states."""
    _MockGrammarHandler._improve_delay_ms = 500
    yield
    _MockGrammarHandler._improve_delay_ms = 0
