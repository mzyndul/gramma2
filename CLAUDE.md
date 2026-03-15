# CLAUDE.md

## Project Overview
Gramma2 — an open-source browser writing assistant. Chrome extension (Manifest V3) + Python FastAPI server. User focuses a text input on any web page, clicks a floating icon, picks a backend (Ollama or Codex), and gets a corrected suggestion displayed in a popup for one-click replacement. Long text is reviewed progressively in sentence-aligned blocks.

## Environment Setup
- Python 3.13.7
- Always use venv — never install packages into system Python:
  ```bash
  cd /home/mzyndul/projects/gramma2
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- Dependencies: `pytest`, `pytest-playwright`, `fastapi`, `uvicorn[standard]`, `httpx`
- Browser: `playwright install chromium` (installs full Chromium, not just headless shell)

## Running Tests
Always activate venv first: `source .venv/bin/activate`

```bash
# Server unit tests
python3 -m pytest tests/test_server.py -v

# E2E tests (browser opens visibly — extensions require headed mode)
python3 -m pytest tests/test_e2e.py -v

# All tests
python3 -m pytest tests/ -v
```

The real server must not be running on port 8555 when running tests.

## Key Technical Decisions
- **Server**: FastAPI + Uvicorn on port 8555, with in-memory LRU cache (SHA-256 keyed, 1h TTL)
- **LLM backends**: Ollama (default, local) or Codex CLI (optional, remote). Configurable via env vars `GRAMMA2_OLLAMA_MODEL`, `GRAMMA2_CODEX_MODEL`.
- **Startup validation**: Ollama must be reachable or server exits. Codex is checked but optional.
- **Extension**: Manifest V3, unpacked developer mode, loaded via `chrome://extensions`
- **CORS bypass**: Background service worker makes fetch to server (not content script directly)
- **Review UX**: Single suggestion with explicit accept/reject. Progressive review for long text.
- **Testing**: pytest-playwright with `launch_persistent_context` for Chrome extension loading

## Playwright + Chrome Extensions
- **MCP Playwright plugin is NOT suitable** for this project — it cannot load Chrome extensions (no custom browser launch args) and blocks `file://` URLs
- Must use **pytest-playwright** (Python) with `launch_persistent_context` and args:
  - `--load-extension=<path>` and `--disable-extensions-except=<path>`
  - `headless=False` is required — Chrome extensions don't work in headless mode
- For CI/headless: use `xvfb-run`
- **Timing pitfall**: When focus moves between elements, the icon briefly hides. Always use `expect(...).to_be_visible(timeout=2000)` before calling `bounding_box()` — never use `wait_for_timeout()` for this, as `bounding_box()` returns `None` on hidden elements

## Project Structure
```
gramma2/
├── server/           # FastAPI server (app, backends, cache, service)
├── extension/        # Chrome Manifest V3 extension
├── tests/            # Server unit tests + Playwright e2e tests
└── .venv/            # Python virtual environment (gitignored)
```
