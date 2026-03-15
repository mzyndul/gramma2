import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .backends import BACKENDS
from .service import improve_single, improve_batch

log = logging.getLogger("gramma2")

app = FastAPI(title="Gramma2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=400, content={"error": "invalid request"})


class ImproveRequest(BaseModel):
    text: str = ""
    backend: str = "local"


class BatchRequest(BaseModel):
    sentences: list[str] = []
    backend: str = "local"


@app.post("/improve")
def handle_improve(req: ImproveRequest):
    if not req.text or not req.text.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "text field is required and must not be empty"},
        )
    if req.backend not in BACKENDS:
        return JSONResponse(
            status_code=400,
            content={"error": f"unknown backend: {req.backend}"},
        )
    try:
        suggestion = improve_single(req.text, req.backend)
        return {"suggestions": [suggestion]}
    except Exception as e:
        log.exception("ERROR /improve [%s] %r", req.backend, req.text[:60])
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/improve-batch")
def handle_improve_batch(req: BatchRequest):
    if not req.sentences:
        return JSONResponse(
            status_code=400,
            content={"error": "sentences must be a non-empty list"},
        )
    for item in req.sentences:
        if not isinstance(item, str) or not item.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "each sentence must be a non-empty string"},
            )
    if req.backend not in BACKENDS:
        return JSONResponse(
            status_code=400,
            content={"error": f"unknown backend: {req.backend}"},
        )
    try:
        results = improve_batch(req.sentences, req.backend)
        return {"results": results}
    except Exception as e:
        log.exception("ERROR /improve-batch [%s] %d sentences", req.backend, len(req.sentences))
        return JSONResponse(status_code=500, content={"error": str(e)})
