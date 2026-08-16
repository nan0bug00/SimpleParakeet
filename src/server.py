"""
OpenAI-compatible Whisper transcription service backed by Sherpa ONNX.

The Whisper client owns microphone/PTT/VAD capture. Each completed upload is
decoded once by the reusable offline Parakeet v3 recognizer; this deliberately
does not repeatedly decode a growing open-mic buffer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from asr import ASRError, DEFAULT_ONNX_THREADS, MODEL_NAME, ParakeetRecognizer
from audio import decode_to_wav16k_mono, wav16k_mono_to_float
from lexicon import SkyrimLexicon
from model_install import ensure_model

MODEL_ID = os.environ.get("PARAKEET_MODEL_ID", "whisper-1")
HOST_MODEL_NAME = os.environ.get("PARAKEET_DISPLAY_NAME", MODEL_NAME)
LOG = logging.getLogger("simpleparakeet")


def _root_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(os.environ.get("PARAKEET_ROOT", Path.cwd())) / path


@asynccontextmanager
async def lifespan(application: FastAPI):
    model_dir = _root_relative(os.environ.get("PARAKEET_MODEL_DIR") or "models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
    threads = int(os.environ.get("PARAKEET_ONNX_THREADS", DEFAULT_ONNX_THREADS))
    lexicon_file = _root_relative(os.environ.get("PARAKEET_LEXICON_FILE", "lexicon.json"))
    try:
        enabled = os.environ.get("PARAKEET_LEXICON_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
        lexicon = SkyrimLexicon.load(
            lexicon_file,
            threshold=float(os.environ.get("PARAKEET_LEXICON_THRESHOLD", "0.89")),
            margin=float(os.environ.get("PARAKEET_LEXICON_MARGIN", "0.10")),
        ) if enabled else SkyrimLexicon()
    except ValueError as exc:
        LOG.warning("Lexicon disabled: %s", exc)
        lexicon = SkyrimLexicon()
    recognizer = ParakeetRecognizer(model_dir, threads)
    started = time.perf_counter()
    try:
        ensure_model(model_dir)
        recognizer.initialize()
    except ASRError as exc:
        # Fail startup with a useful error instead of accepting requests that all fail.
        raise RuntimeError(str(exc)) from exc
    application.state.recognizer = recognizer
    application.state.lexicon = lexicon
    LOG.info("Parakeet v3 initialized in %.2fs using %s ONNX threads", time.perf_counter() - started, threads)
    yield

app = FastAPI(title="SimpleParakeet", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_timestamp_granularities(
    raw: list[str] | str | None,
) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [p for p in raw.split(",") if p]
    out: list[str] = []
    for item in raw:
        out.extend(p for p in str(item).split(",") if p)
    return out


def _extract_text(payload: Any) -> str:
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text
    if isinstance(payload, str):
        return payload
    return ""


def _sse_pack(event_type: str, data: dict[str, Any]) -> bytes:
    body = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {body}\n\n".encode("utf-8")


def _fake_sse_chunks(text: str) -> Iterable[bytes]:
    """
    Emit OpenAI-style transcript SSE after inference completes.
    Word-split deltas so clients that accumulate deltas still work.
    """
    parts = text.split(" ") if text else [""]
    rebuilt: list[str] = []
    for i, part in enumerate(parts):
        piece = part if i == 0 else f" {part}"
        rebuilt.append(piece)
        yield _sse_pack(
            "transcript.text.delta",
            {"type": "transcript.text.delta", "delta": piece},
        )
    yield _sse_pack(
        "transcript.text.done",
        {"type": "transcript.text.done", "text": text},
    )
    yield b"data: [DONE]\n\n"


async def _stream_fake_sse(text: str) -> AsyncIterator[bytes]:
    for chunk in _fake_sse_chunks(text):
        yield chunk


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": HOST_MODEL_NAME,
        "backend": "sherpa-onnx",
        "onnx_threads": app.state.recognizer.num_threads,
    }


@app.get("/v1/models")
@app.get("/models")
async def list_models() -> dict[str, Any]:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": now,
                "owned_by": "local",
            },
            {
                "id": HOST_MODEL_NAME,
                "object": "model",
                "created": now,
                "owned_by": "local",
            },
            {
                "id": "parakeet",
                "object": "model",
                "created": now,
                "owned_by": "local",
            },
        ],
    }


async def _handle_transcription(
    request: Request,
    file: UploadFile,
    model: str,
    language: str | None,
    prompt: str | None,
    response_format: str,
    temperature: str | None,
    stream: str | None,
    sample_rate: int,
    channels: int,
    encoding: str | None,
    timestamp_granularities: list[str] | None,
) -> Response:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file upload")

    force_pcm = (encoding or "").lower() in {"pcm", "pcm16", "s16le", "raw"}
    # Also honor query/header hints some clients send
    if request.query_params.get("encoding", "").lower() in {"pcm", "pcm16", "s16le"}:
        force_pcm = True

    try:
        wav_bytes = decode_to_wav16k_mono(
            raw,
            filename=file.filename,
            content_type=file.content_type,
            sample_rate=sample_rate,
            channels=channels,
            force_pcm=force_pcm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    want_stream = _truthy(stream)
    try:
        started = time.perf_counter()
        text = request.app.state.recognizer.transcribe(wav16k_mono_to_float(wav_bytes))
        asr_seconds = time.perf_counter() - started
        corrected = request.app.state.lexicon.correct(text)
        LOG.debug("Transcribed %.2fs; lexicon changed=%s", asr_seconds, corrected != text)
        text = corrected
    except (ASRError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    payload: dict[str, Any] = {"text": text, "task": "transcribe", "language": language or "en"}

    if want_stream:
        return StreamingResponse(
            _stream_fake_sse(text),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if response_format == "text":
        return PlainTextResponse(text)

    if response_format == "verbose_json":
        # Ensure OpenAI-ish verbose shape even if upstream is minimal
        if isinstance(payload, dict) and "segments" not in payload:
            duration = payload.get("duration")
            payload = {
                **payload,
                "task": payload.get("task", "transcribe"),
                "language": payload.get("language", language or "en"),
                "duration": duration,
                "segments": [
                    {
                        "id": 0,
                        "seek": 0,
                        "start": 0.0,
                        "end": duration if isinstance(duration, (int, float)) else 0.0,
                        "text": text,
                        "tokens": [],
                        "temperature": 0.0,
                        "avg_logprob": 0.0,
                        "compression_ratio": 0.0,
                        "no_speech_prob": 0.0,
                    }
                ],
            }
        return JSONResponse(payload)

    # default json
    return JSONResponse({"text": text})


@app.post("/v1/audio/transcriptions")
@app.post("/audio/transcriptions")
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(default=MODEL_ID),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    response_format: str = Form(default="json"),
    temperature: str | None = Form(default=None),
    stream: str | None = Form(default=None),
    # Non-standard but useful for raw PCM uploads
    sample_rate: int = Form(default=16000),
    channels: int = Form(default=1),
    encoding: str | None = Form(default=None),
):
    # Collect timestamp_granularities[] from form (may appear multiple times)
    form = await request.form()
    gran_raw = form.getlist("timestamp_granularities[]") or form.getlist(
        "timestamp_granularities"
    )
    granules = _parse_timestamp_granularities([str(x) for x in gran_raw] or None)

    return await _handle_transcription(
        request=request,
        file=file,
        model=model,
        language=language,
        prompt=prompt,
        response_format=(response_format or "json").strip().lower(),
        temperature=temperature,
        stream=stream,
        sample_rate=int(sample_rate or 16000),
        channels=int(channels or 1),
        encoding=encoding,
        timestamp_granularities=granules,
    )


# Bearer tokens are accepted and ignored (SkyrimNet / OpenAI clients send them).


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="SimpleParakeet Whisper API")
    parser.add_argument("--host", default=os.environ.get("PARAKEET_API_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PARAKEET_API_PORT", "8210")),
    )
    args = parser.parse_args()

    # Frozen exe: pass app object. Dev: import string is fine too.
    uvicorn.run(app, host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
