import logging
import uvicorn

from .backends import warmup_model, check_codex_available, OLLAMA_MODEL, CODEX_MODEL


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    warmup_model()
    has_codex = check_codex_available()

    backends = [f"local ({OLLAMA_MODEL})"]
    if has_codex:
        backends.append(f"codex ({CODEX_MODEL})")
    backends.append("fake")

    print(f"Gramma2 server starting on http://127.0.0.1:8555", flush=True)
    print(f"Backends: {', '.join(backends)}", flush=True)
    uvicorn.run("server.app:app", host="127.0.0.1", port=8555)


if __name__ == "__main__":
    main()
