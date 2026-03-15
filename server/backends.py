import json
import os
import subprocess
import sys
import urllib.request

from .prompt import PROMPT_TEMPLATE

OLLAMA_URL = os.environ.get("GRAMMA2_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("GRAMMA2_OLLAMA_MODEL", "qwen2.5:3b")
CODEX_MODEL = os.environ.get("GRAMMA2_CODEX_MODEL", "o4-mini")

BACKENDS = {"local", "codex", "fake"}


def _parse_suggestion(output: str) -> str:
    if output.startswith("```json"):
        output = output[len("```json"):]
    if output.startswith("```"):
        output = output[len("```"):]
    if output.endswith("```"):
        output = output[:-len("```")]
    output = output.strip()

    data = json.loads(output)
    suggestion = data.get("suggestion")
    if not isinstance(suggestion, str) or not suggestion.strip():
        raise ValueError(f"Expected a 'suggestion' string, got: {type(suggestion)}")
    return suggestion


def call_local(text: str) -> str:
    prompt_text = PROMPT_TEMPLATE.format(text=text)
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt_text,
        "stream": False,
        "format": "json",
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    return _parse_suggestion(result["response"])


def call_codex(text: str) -> str:
    prompt_text = PROMPT_TEMPLATE.format(text=text)
    proc = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", "--ephemeral",
         "--dangerously-bypass-approvals-and-sandbox", "-m", CODEX_MODEL, "-"],
        input=prompt_text,
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Codex failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return _parse_suggestion(proc.stdout)


def call_fake(text: str) -> str:
    return f"Fixed: {text}"


def get_backend(name: str):
    backends = {"local": call_local, "codex": call_codex, "fake": call_fake}
    if name not in backends:
        raise ValueError(f"unknown backend: {name}")
    return backends[name]


def model_for_backend(backend: str) -> str:
    if backend == "local":
        return OLLAMA_MODEL
    if backend == "codex":
        return CODEX_MODEL
    return "fake"


def warmup_model() -> None:
    print(f"Warming up Ollama model '{OLLAMA_MODEL}' at {OLLAMA_URL}...", flush=True)
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": "Hi",
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
        print(f"Ollama ready: model '{OLLAMA_MODEL}' loaded.", flush=True)
    except Exception as e:
        print(f"\nERROR: Cannot reach Ollama at {OLLAMA_URL}", flush=True)
        print(f"  Details: {e}", flush=True)
        print(f"\n  Make sure Ollama is running ('ollama serve') and the model is pulled:", flush=True)
        print(f"    ollama pull {OLLAMA_MODEL}\n", flush=True)
        sys.exit(1)


def check_codex_available() -> bool:
    try:
        proc = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            version = proc.stdout.strip()
            print(f"Codex CLI available: {version}", flush=True)
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass
    print("Codex CLI not found (optional — Ollama will be the default backend).", flush=True)
    return False
