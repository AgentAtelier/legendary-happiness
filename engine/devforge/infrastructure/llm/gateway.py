"""LLM Gateway — single proxy owning the connection to llama.cpp.

Brokers port ``:9090`` and forwards all LLM requests to llama.cpp on
``:8080`` through a single shared ``httpx.AsyncClient`` connection pool.
Both Odysseus (``/v1/chat/completions``) and DevForge (``/completion``,
``/tokenize``) connect through the gateway instead of hitting llama.cpp
directly, eliminating the two-client KV-cache thrashing problem.

Phase 3: prefix-affinity scheduling for KV-cache reuse.
    Streaming Odysseus requests hold llama.cpp cache slots open.
    Incoming DevForge ``/completion`` requests are serialized behind
    active streams so their different prompt prefix doesn't evict the
    conversation's hot KV-cache entries.

Phase 2: per-turn token budget via ``X-Turn-Id`` header.

Usage::

    python -m devforge.infrastructure.llm.gateway

Or programmatically::

    import uvicorn
    from devforge.infrastructure.llm.gateway import app
    uvicorn.run(app, host="127.0.0.1", port=9090)
"""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ── Config ──────────────────────────────────────────────────────

LLAMA_CPP_URL = os.environ.get("LLAMA_CPP_URL", "http://localhost:8080")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "9090"))
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "127.0.0.1")

# Per-turn token budget (Phase 2)
BUDGET_LIMIT_TOKENS = int(os.environ.get("GATEWAY_BUDGET_TOKENS", "100000"))
TURN_EXPIRY_SECONDS = int(os.environ.get("GATEWAY_TURN_EXPIRY", "300"))
# When set, requests without X-Turn-Id are rejected (strict mode).
# When unset (default), untagged requests share a default bucket.
GATEWAY_STRICT_BUDGET = os.environ.get("GATEWAY_STRICT_BUDGET", "0") == "1"
# Key for the shared default bucket (untagged requests)
_DEFAULT_BUCKET = "__default__"

# Prefix-affinity scheduling (Phase 3)
GATEWAY_SERIALIZE_DEVFORGE = os.environ.get("GATEWAY_SERIALIZE_DEVFORGE", "1") == "1"
GATEWAY_DEVFORGE_QUEUE_TIMEOUT = float(os.environ.get("GATEWAY_DEVFORGE_QUEUE_TIMEOUT", "60"))

# Connection pool: keep connections warm to llama.cpp so repeat calls
# skip the TCP+TLS handshake.  Max 20 connections — enough for
# concurrent Odysseus streams + DevForge calls without overwhelming
# llama.cpp's thread pool.
_HTTP_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=30.0,
)

logger = logging.getLogger("llm_gateway")

# ── Shared HTTP client ──────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None
_init_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    """Return the process-wide AsyncClient (lazy init, thread-safe)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        return _http_client
    async with _init_lock:
        if _http_client is not None and not _http_client.is_closed:
            return _http_client
        _http_client = httpx.AsyncClient(
            limits=_HTTP_LIMITS,
            http2=False,
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
        )
    return _http_client


def _gateway_error(status: int, detail: str) -> HTTPException:
    """Standardized error response for upstream failures."""
    return HTTPException(status_code=status, detail=detail)


def _safe_json(resp: httpx.Response) -> dict | list:
    """Parse upstream response as JSON, falling back to a dict on failure.

    If llama.cpp returns a non-JSON error page (e.g. HTML 502), this
    returns ``{"error": "...", "upstream_status": ...}`` instead of
    crashing with ``JSONDecodeError``.
    """
    try:
        return resp.json()
    except Exception:
        logger.warning(
            "Gateway: upstream returned non-JSON response (status=%d, content_type=%s)",
            resp.status_code,
            resp.headers.get("content-type", "?"),
        )
        return {
            "error": "Upstream returned non-JSON response",
            "upstream_status": resp.status_code,
        }


async def _read_json_body(request: Request) -> dict:
    """Read and parse the request body as JSON, raising 400 on failure."""
    try:
        return await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")


# ── Per-turn budget tracking (Phase 2) ──────────────────────────


@dataclass
class _TurnBudget:
    """Cumulative token usage for one ``apply_spec`` turn."""

    tokens_used: int = 0
    call_count: int = 0
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.monotonic()


# Map: turn_id → _TurnBudget. Async handlers share the event-loop
# thread, so plain dict access is safe without a lock.
_turn_budgets: dict[str, _TurnBudget] = {}


def _check_budget(turn_id: str) -> _TurnBudget:
    """Return the budget entry for *turn_id*, raising 429 if exceeded.

    Creates a new entry for unseen turn IDs. Expired entries are
    purged on lookup — a turn that outlives its inactivity window
    (sliding expiry, reset on every ``_record_usage``) gets a fresh
    budget.
    """
    entry = _turn_budgets.get(turn_id)

    # Purge expired entries (sliding window: last activity, not creation)
    if entry is not None:
        age = time.monotonic() - entry.created_at
        if age > TURN_EXPIRY_SECONDS:
            logger.info(
                "Budget: purging expired turn %s (age=%.0fs, tokens=%d, calls=%d)",
                turn_id[:8],
                age,
                entry.tokens_used,
                entry.call_count,
            )
            del _turn_budgets[turn_id]
            entry = None

    if entry is None:
        entry = _TurnBudget()
        _turn_budgets[turn_id] = entry
        logger.debug("Budget: new turn %s", turn_id[:8])

    remaining = max(0, BUDGET_LIMIT_TOKENS - entry.tokens_used)
    if entry.tokens_used >= BUDGET_LIMIT_TOKENS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Token budget exceeded for turn {turn_id[:8]}: "
                f"{entry.tokens_used}/{BUDGET_LIMIT_TOKENS} tokens "
                f"used across {entry.call_count} calls"
            ),
        )

    return entry


def _record_usage(turn_id: str, tokens: int) -> None:
    """Record token usage for a turn (best-effort, never raises).

    Resets the expiry timer on every call — sliding window so active
    turns don't expire mid-pipeline.
    """
    if tokens <= 0:
        return
    entry = _turn_budgets.get(turn_id)
    if entry is None:
        return
    entry.tokens_used += tokens
    entry.call_count += 1
    entry.created_at = time.monotonic()  # sliding expiry
    logger.debug(
        "Budget: turn %s +%d tokens → %d/%d (%d calls)",
        turn_id[:8],
        tokens,
        entry.tokens_used,
        BUDGET_LIMIT_TOKENS,
        entry.call_count,
    )


def _extract_tokens_completion(data: dict) -> int:
    """Extract total token count from a llama.cpp /completion response."""
    # /completion returns timings.prompt_n (tokens evaluated) and
    # timings.predicted_n (tokens generated).  If timing info is
    # missing, fall back to tokens_evaluated + tokens_predicted.
    timings = data.get("timings") or {}
    prompt_n = timings.get("prompt_n", 0)
    predicted_n = timings.get("predicted_n", 0)
    if prompt_n or predicted_n:
        return prompt_n + predicted_n
    # Fallback fields
    return data.get("tokens_evaluated", 0) + data.get("tokens_predicted", 0)


def _extract_tokens_chat(data: dict) -> int:
    """Extract total token count from a /v1/chat/completions response."""
    usage = data.get("usage") or {}
    return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)


async def _cleanup_stale_budgets() -> None:
    """Background task: purge turn budgets older than TURN_EXPIRY_SECONDS."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        stale = [tid for tid, b in _turn_budgets.items() if now - b.created_at > TURN_EXPIRY_SECONDS]
        for tid in stale:
            b = _turn_budgets.pop(tid, None)
            if b:
                logger.info(
                    "Budget: cleaned up turn %s (tokens=%d, calls=%d)",
                    tid[:8],
                    b.tokens_used,
                    b.call_count,
                )


def _get_turn_id(request: Request) -> str | None:
    """Extract X-Turn-Id from request headers, if present."""
    return request.headers.get("X-Turn-Id")


# ── Prefix-affinity scheduling (Phase 3) ────────────────────────

# Streaming requests hold llama.cpp cache slots open.  DevForge
# /completion requests are serialized behind active streams so their
# different prompt prefix doesn't evict the conversation's hot
# KV-cache entries.
#
# No lock needed — asyncio is single-threaded; synchronous
# increment/decrement of a plain int cannot be preempted.

_active_stream_count: int = 0
_streams_done: asyncio.Event = asyncio.Event()
_streams_done.set()  # initially: no active streams → "done"

# Stats for the /scheduler debug endpoint
_streams_total: int = 0
_devforge_queued_total: int = 0
_devforge_queued_timeout_total: int = 0


def _stream_start() -> None:
    """Register the start of a streaming request (plain def, not async)."""
    global _active_stream_count, _streams_total
    _active_stream_count += 1
    _streams_total += 1
    _streams_done.clear()


def _stream_end() -> None:
    """Register the end of a streaming request."""
    global _active_stream_count
    _active_stream_count -= 1
    if _active_stream_count == 0:
        _streams_done.set()


async def _wait_for_streams(timeout: float) -> None:
    """Block until all active streams finish, or *timeout* seconds elapse.

    Uses ``asyncio.timeout`` (Python 3.11+) to enforce the deadline
    while looping after every wakeup to guard against a new stream
    starting between ``set()`` and this coroutine resuming.
    """
    global _devforge_queued_total, _devforge_queued_timeout_total
    try:
        async with asyncio.timeout(timeout):
            while _active_stream_count > 0:
                _devforge_queued_total += 1
                await _streams_done.wait()
    except TimeoutError:
        _devforge_queued_timeout_total += 1
        logger.warning(
            "Scheduler: DevForge /completion waited %.0fs for %d stream(s) — proceeding anyway (KV cache may evict)",
            timeout,
            _active_stream_count,
        )


def _prefix_hash(body: dict, route: str) -> str:
    """Compute a short hash of the request's prompt prefix.

    Used for monitoring which requests share prefixes (would benefit
    from cache reuse).  Not used for enforcement in this phase.
    """
    if route == "completion":
        text = str(body.get("prompt", ""))[:1000]
    elif route == "chat":
        messages = body.get("messages", [])
        text = str(messages[:2])[:1000] if messages else ""
    else:
        text = ""
    if not text:
        return "none"
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:8]


# ── App ─────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: log that we're ready.  Shutdown: close the client pool."""
    logger.info(
        "LLM Gateway starting on %s:%s → %s (budget=%d tokens/turn, "
        "expiry=%ds, serialize_devforge=%s, queue_timeout=%ds)",
        GATEWAY_HOST,
        GATEWAY_PORT,
        LLAMA_CPP_URL,
        BUDGET_LIMIT_TOKENS,
        TURN_EXPIRY_SECONDS,
        GATEWAY_SERIALIZE_DEVFORGE,
        int(GATEWAY_DEVFORGE_QUEUE_TIMEOUT),
    )
    cleanup_task = asyncio.create_task(_cleanup_stale_budgets())
    yield
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("LLM Gateway shut down")


app = FastAPI(
    title="LLM Gateway",
    description="Proxies requests to llama.cpp with shared connection pooling, per-turn token budgets, and prefix-affinity scheduling",
    version="0.3.0",
    lifespan=_lifespan,
)


# ── Health check ────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Quick health probe — checks that llama.cpp is reachable."""
    try:
        client = await _get_client()
        start = time.monotonic()
        resp = await client.get(f"{LLAMA_CPP_URL}/health")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return JSONResponse(
            {
                "status": "ok",
                "llama_cpp": {
                    "reachable": resp.is_success,
                    "status_code": resp.status_code,
                    "latency_ms": elapsed_ms,
                },
            }
        )
    except Exception as exc:
        return JSONResponse(
            {
                "status": "degraded",
                "llama_cpp": {"reachable": False, "error": str(exc)},
            },
            status_code=503,
        )


# ── Slot monitoring ─────────────────────────────────────────────


@app.get("/slots")
async def slots():
    """Proxy llama.cpp's /slots endpoint for KV-cache monitoring."""
    try:
        client = await _get_client()
        resp = await client.get(f"{LLAMA_CPP_URL}/slots")
        return JSONResponse(_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError:
        raise _gateway_error(503, "Cannot reach llama.cpp")
    except httpx.ReadTimeout:
        raise _gateway_error(504, "llama.cpp read timeout")


# ── Tokenize ────────────────────────────────────────────────────


@app.post("/tokenize")
async def tokenize(request: Request):
    """Proxy llama.cpp's /tokenize endpoint for accurate token counts."""
    turn_id = _get_turn_id(request) or _DEFAULT_BUCKET
    if GATEWAY_STRICT_BUDGET and turn_id == _DEFAULT_BUCKET:
        raise HTTPException(
            status_code=400,
            detail="X-Turn-Id header required in strict budget mode",
        )
    _check_budget(turn_id)

    body = await _read_json_body(request)

    try:
        client = await _get_client()
        resp = await client.post(f"{LLAMA_CPP_URL}/tokenize", json=body)
        data = _safe_json(resp)
        if turn_id:
            # /tokenize returns a list of token IDs — count them as
            # prompt-equivalent tokens for budget tracking (cheap, but
            # keeps the budget comprehensive).
            tokens = data.get("tokens", [])
            if isinstance(tokens, list):
                _record_usage(turn_id, len(tokens))
        remaining = max(0, BUDGET_LIMIT_TOKENS - _turn_budgets.get(turn_id, _TurnBudget()).tokens_used)
        return JSONResponse(data, status_code=resp.status_code, headers={"X-Budget-Remaining": str(remaining)})
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise _gateway_error(503, "Cannot reach llama.cpp")
    except httpx.ReadTimeout:
        raise _gateway_error(504, "llama.cpp read timeout")


# ── Completion (DevForge) ───────────────────────────────────────


@app.post("/completion")
async def completion(request: Request):
    """Proxy llama.cpp's native /completion endpoint.

    Used by DevForge's LlamaClient for GBNF-grammar-constrained
    generation (planner, compiler, verifier).

    If streaming requests are active, this call is serialized behind
    them (Phase 3) to avoid evicting their hot KV-cache entries.
    """
    turn_id = _get_turn_id(request) or _DEFAULT_BUCKET
    if GATEWAY_STRICT_BUDGET and turn_id == _DEFAULT_BUCKET:
        raise HTTPException(
            status_code=400,
            detail="X-Turn-Id header required in strict budget mode",
        )
    _check_budget(turn_id)

    # Read body BEFORE waiting for streams (Phase 3).
    # ``await request.json()`` yields to the event loop — a new
    # stream could start during that yield and invalidate the
    # scheduling decision.  Reading the body upfront closes that gap.
    body = await _read_json_body(request)

    # Phase 3: serialise behind active streams to preserve KV cache
    if GATEWAY_SERIALIZE_DEVFORGE and _active_stream_count > 0:
        logger.info(
            "Scheduler: /completion queued behind %d stream(s)",
            _active_stream_count,
        )
        await _wait_for_streams(GATEWAY_DEVFORGE_QUEUE_TIMEOUT)

    try:
        client = await _get_client()

        _phash = _prefix_hash(body, "completion")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Scheduler: /completion prefix=%s", _phash)

        resp = await client.post(
            f"{LLAMA_CPP_URL}/completion",
            json=body,
            timeout=120.0,
        )
        data = _safe_json(resp)

        if turn_id:
            tokens = _extract_tokens_completion(data)
            _record_usage(turn_id, tokens)

        remaining = max(0, BUDGET_LIMIT_TOKENS - _turn_budgets.get(turn_id, _TurnBudget()).tokens_used)
        return JSONResponse(data, status_code=resp.status_code, headers={"X-Budget-Remaining": str(remaining)})
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise _gateway_error(503, "Cannot reach llama.cpp")
    except httpx.ReadTimeout:
        raise _gateway_error(504, "llama.cpp read timeout")


# ── Models list (Odysseus endpoint probing) ────────────────────


@app.get("/v1/models")
async def list_models():
    """Proxy llama.cpp's /v1/models endpoint for model listing.

    Odysseus calls this during endpoint probing to discover available
    model IDs before sending chat requests.
    """
    try:
        client = await _get_client()
        resp = await client.get(f"{LLAMA_CPP_URL}/v1/models")
        return JSONResponse(_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError:
        raise _gateway_error(503, "Cannot reach llama.cpp")
    except httpx.ReadTimeout:
        raise _gateway_error(504, "llama.cpp read timeout")


# ── Chat completions (Odysseus) ─────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Proxy the OpenAI-compatible /v1/chat/completions endpoint.

    Used by Odysseus for streaming agent tool calls.  Streams the
    response back chunk-by-chunk to preserve the SSE protocol.
    """
    turn_id = _get_turn_id(request) or _DEFAULT_BUCKET
    if GATEWAY_STRICT_BUDGET and turn_id == _DEFAULT_BUCKET:
        raise HTTPException(
            status_code=400,
            detail="X-Turn-Id header required in strict budget mode",
        )
    _check_budget(turn_id)

    body = await _read_json_body(request)
    is_stream = body.get("stream", False)

    if not is_stream:
        # Non-streaming: simple proxy.
        #
        # Track as an active stream (Phase 3) — non-streaming chat
        # still evaluates a prompt and can evict KV-cache entries.
        _stream_start()
        try:
            client = await _get_client()
            resp = await client.post(
                f"{LLAMA_CPP_URL}/v1/chat/completions",
                json=body,
                timeout=300.0,
            )
            data = _safe_json(resp)

            if turn_id:
                tokens = _extract_tokens_chat(data)
                _record_usage(turn_id, tokens)

            return JSONResponse(data, status_code=resp.status_code)
        except HTTPException:
            raise
        except httpx.ConnectError:
            raise _gateway_error(503, "Cannot reach llama.cpp")
        except httpx.ReadTimeout:
            raise _gateway_error(504, "llama.cpp read timeout")
        finally:
            _stream_end()

    # Streaming: proxy SSE chunks (usage extracted from final chunk).
    #
    # Register the stream lifecycle NOW (Phase 3) — *before* returning
    # the StreamingResponse.  Async generators don't begin executing
    # until Starlette iterates them, so calling _stream_start() inside
    # the generator would leave a window where DevForge /completion
    # requests bypass the queue.
    _stream_start()
    try:
        return StreamingResponse(
            _stream_chat_completions(body, turn_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        _stream_end()
        raise


async def _stream_chat_completions(body: dict, turn_id: str | None = None):
    """Forward streaming chat completions chunk-by-chunk.

    If *turn_id* is set, the final SSE usage chunk is intercepted to
    record token consumption for budget tracking.

    The caller MUST have called ``_stream_start()`` before returning
    the ``StreamingResponse`` that wraps this generator.  Only
    ``_stream_end()`` is called in the ``finally`` block here.
    """
    try:
        client = await _get_client()

        _phash = _prefix_hash(body, "chat")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Scheduler: stream start prefix=%s (active=%d)", _phash, _active_stream_count)

        async with client.stream(
            "POST",
            f"{LLAMA_CPP_URL}/v1/chat/completions",
            json=body,
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
        ) as resp:
            if resp.status_code != 200:
                yield f"event: error\ndata: {_json.dumps({'status': resp.status_code, 'error': f'llama.cpp returned {resp.status_code}'})}\n\n"
                return

            async for line in resp.aiter_lines():
                if line:
                    # Intercept usage chunk for budget tracking
                    if turn_id and line.startswith("data: "):
                        data_str = line[6:]
                        if '"usage"' in data_str or '"usage":' in data_str:
                            try:
                                chunk = _json.loads(data_str)
                                usage = chunk.get("usage")
                                if isinstance(usage, dict):
                                    tokens = usage.get(
                                        "prompt_tokens",
                                        0,
                                    ) + usage.get("completion_tokens", 0)
                                    _record_usage(turn_id, tokens)
                            except Exception:
                                pass
                    yield line + "\n"
                # Skip empty lines between SSE events.
    except httpx.ConnectError:
        yield 'event: error\ndata: {"error": "Cannot reach llama.cpp", "status": 503}\n\n'
    except httpx.ReadTimeout:
        yield 'event: error\ndata: {"error": "Read timeout from llama.cpp", "status": 504}\n\n'
    except Exception as exc:
        logger.error("Stream proxy error: %s", exc)
        yield f"event: error\ndata: {_json.dumps({'error': 'Gateway stream error', 'status': 502})}\n\n"
    finally:
        _stream_end()


# ── Budget debug endpoint ───────────────────────────────────────


@app.get("/budget")
async def budget_overview():
    """Return current budget state for all active turns."""
    now = time.monotonic()
    turns = []
    for tid, b in sorted(_turn_budgets.items()):
        turns.append(
            {
                "turn_id": tid[:8] + "…",
                "tokens_used": b.tokens_used,
                "budget_limit": BUDGET_LIMIT_TOKENS,
                "remaining": max(0, BUDGET_LIMIT_TOKENS - b.tokens_used),
                "call_count": b.call_count,
                "age_s": round(now - b.created_at, 1),
            }
        )
    return JSONResponse(
        {
            "active_turns": len(turns),
            "budget_limit": BUDGET_LIMIT_TOKENS,
            "turn_expiry_s": TURN_EXPIRY_SECONDS,
            "turns": turns,
        }
    )


# ── Scheduler debug endpoint (Phase 3) ──────────────────────────


@app.get("/scheduler")
async def scheduler_overview():
    """Return current scheduler state: active streams and queue stats."""
    return JSONResponse(
        {
            "active_streams": _active_stream_count,
            "streams_total": _streams_total,
            "devforge_queued_total": _devforge_queued_total,
            "devforge_queued_timeout_total": _devforge_queued_timeout_total,
            "serialize_devforge": GATEWAY_SERIALIZE_DEVFORGE,
            "queue_timeout_s": GATEWAY_DEVFORGE_QUEUE_TIMEOUT,
        }
    )


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s | %(message)s",
    )
    logger.info("LLM Gateway → %s", LLAMA_CPP_URL)
    uvicorn.run(
        "devforge.infrastructure.llm.gateway:app",
        host=GATEWAY_HOST,
        port=GATEWAY_PORT,
        log_level="info",
    )
