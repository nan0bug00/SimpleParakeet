"""
OpenAI-compatible Whisper transcription front-end for parakeet.cpp.

Accepts the usual multipart Whisper upload (including raw PCM16), decodes to
16 kHz mono WAV, proxies inference to the local parakeet-server, and optionally
emits a fake SSE stream (full transcript as deltas + done).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator, Iterable

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from audio import decode_to_wav16k_mono

PARAKEET_UPSTREAM = os.environ.get(
    "PARAKEET_UPSTREAM", "http://127.0.0.1:8142/v1/audio/transcriptions"
).strip().rstrip("/")
# cmd.exe `set VAR=value & ...` can leave a trailing space in the value; strip handles that.
if not PARAKEET_UPSTREAM.endswith("/audio/transcriptions"):
    # allow base like http://127.0.0.1:8142/v1
    if PARAKEET_UPSTREAM.endswith("/v1"):
        PARAKEET_UPSTREAM = PARAKEET_UPSTREAM + "/audio/transcriptions"
    else:
        PARAKEET_UPSTREAM = PARAKEET_UPSTREAM + "/v1/audio/transcriptions"

MODEL_ID = os.environ.get("PARAKEET_MODEL_ID", "whisper-1")
HOST_MODEL_NAME = os.environ.get("PARAKEET_DISPLAY_NAME", "parakeet-tdt_ctc-110m-f16")

app = FastAPI(title="SimpleParakeet", version="1.0.0")

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


async def _upstream_transcribe(
    wav_bytes: bytes,
    *,
    model: str,
    language: str | None,
    prompt: str | None,
    response_format: str,
    temperature: str | None,
    timestamp_granularities: list[str],
) -> tuple[int, bytes, str]:
    """POST WAV to parakeet-server. Returns status, body, content-type."""
    # Always ask upstream for json/verbose_json — we reshape text/SSE locally.
    upstream_fmt = "verbose_json" if response_format == "verbose_json" else "json"
    multipart: list[tuple[str, tuple[str | None, str] | tuple[str, bytes, str]]] = [
        ("model", (None, model or "parakeet")),
        ("response_format", (None, upstream_fmt)),
    ]
    if language:
        multipart.append(("language", (None, language)))
    if prompt:
        multipart.append(("prompt", (None, prompt)))
    if temperature is not None and temperature != "":
        multipart.append(("temperature", (None, str(temperature))))
    for g in timestamp_granularities:
        multipart.append(("timestamp_granularities[]", (None, g)))
    multipart.append(("file", ("audio.wav", wav_bytes, "audio/wav")))

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(PARAKEET_UPSTREAM, files=multipart)
            ctype = resp.headers.get("content-type", "application/json")
            return resp.status_code, resp.content, ctype
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Cannot reach parakeet-server at {PARAKEET_UPSTREAM}. "
                "Is it running?"
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc


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
    from urllib.parse import urlparse

    upstream_ok = False
    try:
        u = urlparse(PARAKEET_UPSTREAM)
        async with httpx.AsyncClient(timeout=1.5) as client:
            # parakeet-server may 404 on /, but a TCP response means it's up
            await client.get(f"{u.scheme}://{u.netloc}/")
            upstream_ok = True
    except Exception:
        upstream_ok = False
    return {
        "ok": True,
        "model": HOST_MODEL_NAME,
        "upstream": PARAKEET_UPSTREAM,
        "upstream_reachable": upstream_ok,
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
    # Upstream never streams; we always fetch json then reshape.
    upstream_fmt = "verbose_json" if response_format == "verbose_json" else "json"
    status, body, _ctype = await _upstream_transcribe(
        wav_bytes,
        model=model,
        language=language,
        prompt=prompt,
        response_format=upstream_fmt,
        temperature=temperature,
        timestamp_granularities=timestamp_granularities or [],
    )
    if status >= 400:
        detail: Any
        try:
            detail = json.loads(body)
        except Exception:
            detail = body.decode("utf-8", errors="replace")
        raise HTTPException(status_code=status, detail=detail)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        # Unexpected plain text from upstream
        payload = {"text": body.decode("utf-8", errors="replace")}

    if isinstance(payload, dict):
        payload.setdefault("task", "transcribe")
        if language:
            payload.setdefault("language", language)
        else:
            payload.setdefault("language", "en")

    text = _extract_text(payload)

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
