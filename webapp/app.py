"""FastAPI demo app for the OpenAlex semantic-search CLI.

Two surfaces:
  - Live search (`/api/search`): real OpenAlex queries, hard-capped result count,
    per-IP rate limited and TTL-cached. Only needs OPENALEX_API_KEY on the server.
  - Cluster explorer (`/api/examples`): pre-generated datasets served as static
    JSON (no live embedding cost). Generated offline by generate_examples.py.

Run locally:
    .venv/bin/python -m uvicorn webapp.app:app --reload --port 8000
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from openalex_cli.client import OpenAlexClient, OpenAlexError, Work
from openalex_cli.config import load_settings

# --- configuration (overridable via environment) -----------------------------
MAX_RESULTS = int(os.getenv("OA_MAX_RESULTS", "10"))  # hard cap on live search
RATE_PER_MIN = int(os.getenv("OA_RATE_PER_MIN", "20"))
RATE_PER_DAY = int(os.getenv("OA_RATE_PER_DAY", "200"))
CACHE_TTL = int(os.getenv("OA_CACHE_TTL", "3600"))  # seconds
CACHE_MAX = int(os.getenv("OA_CACHE_MAX", "512"))  # entries

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
STATIC_DIR = HERE / "static"
SLUG_RE = re.compile(r"^[a-z0-9-]+$")

SETTINGS = load_settings()


# --- serialization ------------------------------------------------------------
def work_to_dict(w: Work) -> dict:
    """Subset of a Work tailored for the impact table on the frontend."""
    return {
        "id": w.id,
        "title": w.title,
        "year": w.year,
        "doi": w.doi,
        "cited_by_count": w.cited_by_count,
        "fwci": w.fwci,
        "percentile": w.norm_percentile if w.norm_percentile is not None else w.percentile,
        "is_top_1_percent": w.is_top_1_percent,
        "is_top_10_percent": w.is_top_10_percent,
        "field": w.field,
        "domain": w.domain,
        "topic": w.topic,
        "source": w.source,
        "is_oa": w.is_oa,
        "authors": w.authors[:5],
        "relevance": w.relevance,
    }


# --- TTL cache (thread-safe, bounded) -----------------------------------------
class TTLCache:
    def __init__(self, ttl: int, maxsize: int) -> None:
        self.ttl = ttl
        self.maxsize = maxsize
        self._store: "OrderedDict[str, tuple[float, object]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            ts, value = item
            if now - ts > self.ttl:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: object) -> None:
        now = time.monotonic()
        with self._lock:
            self._store[key] = (now, value)
            self._store.move_to_end(key)
            while len(self._store) > self.maxsize:
                self._store.popitem(last=False)


# --- per-IP sliding-window rate limiter ---------------------------------------
class RateLimiter:
    def __init__(self, per_min: int, per_day: int) -> None:
        self.per_min = per_min
        self.per_day = per_day
        self._hits: "dict[str, deque[float]]" = {}
        self._lock = threading.Lock()

    def check(self, ip: str) -> bool:
        """Record a hit; return False if either window is exceeded."""
        now = time.monotonic()
        day_ago = now - 86400
        min_ago = now - 60
        with self._lock:
            q = self._hits.setdefault(ip, deque())
            while q and q[0] < day_ago:
                q.popleft()
            if len(q) >= self.per_day:
                return False
            if sum(1 for t in q if t >= min_ago) >= self.per_min:
                return False
            q.append(now)
            return True


cache = TTLCache(CACHE_TTL, CACHE_MAX)
limiter = RateLimiter(RATE_PER_MIN, RATE_PER_DAY)


def client_ip(request: Request) -> str:
    """Real client IP behind Traefik/Cloudflare (X-Forwarded-For first hop)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- app ----------------------------------------------------------------------
app = FastAPI(title="openalex-cli demo", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "semantic_available": bool(SETTINGS.openalex_api_key),
        "max_results": MAX_RESULTS,
    }


@app.get("/api/search")
def search(request: Request, q: str, mode: str = "semantic", n: int = MAX_RESULTS) -> JSONResponse:
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query.")
    if len(q) > 300:
        raise HTTPException(status_code=400, detail="Query too long.")
    if mode not in ("semantic", "lexical"):
        raise HTTPException(status_code=400, detail="mode must be 'semantic' or 'lexical'.")

    n = max(1, min(n, MAX_RESULTS))  # hard cap
    semantic = mode == "semantic"
    if semantic and not SETTINGS.openalex_api_key:
        raise HTTPException(status_code=503, detail="Semantic search unavailable (no OPENALEX_API_KEY on server).")

    if not limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")

    cache_key = f"{mode}:{n}:{q.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return JSONResponse({"query": q, "mode": mode, "count": len(cached), "results": cached, "cached": True})

    try:
        with OpenAlexClient(api_key=SETTINGS.openalex_api_key, mailto=SETTINGS.mailto) as oa:
            works = oa.search_works(q, semantic=semantic, limit=n, min_impact=True)
    except OpenAlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    results = [work_to_dict(w) for w in works]
    cache.set(cache_key, results)
    return JSONResponse({"query": q, "mode": mode, "count": len(results), "results": results, "cached": False})


@app.get("/api/examples")
def list_examples() -> JSONResponse:
    index = DATA_DIR / "index.json"
    if not index.exists():
        return JSONResponse({"examples": []})
    return JSONResponse(json.loads(index.read_text()))


@app.get("/api/examples/{slug}")
def get_example(slug: str) -> JSONResponse:
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid example id.")
    path = DATA_DIR / f"{slug}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Example not found.")
    return JSONResponse(json.loads(path.read_text()))


# Static frontend mounted last so /api/* routes take precedence.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
