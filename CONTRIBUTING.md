# Contributing to Gramma2

## Setup

```bash
git clone <repository-url>
cd gramma2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

## Running Tests

```bash
source .venv/bin/activate

# Server unit tests
python3 -m pytest tests/test_server.py -v

# End-to-end tests (opens a browser window)
python3 -m pytest tests/test_e2e.py -v

# All tests
python3 -m pytest tests/ -v
```

The real server must not be running on port 8555 when running tests.

## Proposing Changes

1. Fork the repo and create a feature branch
2. Make your changes
3. Add or update tests as needed
4. Run the full test suite
5. Open a pull request against `main`

Keep commits focused and PRs small when possible.
