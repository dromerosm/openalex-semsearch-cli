"""Optional enrichment from the Semantic Scholar (S2) Graph API.

Used for two things OpenAlex does not give reliably on recent papers:
  - the real publication date (OpenAlex often falls back to YYYY-01-01);
  - the influential-citation count.

S2 frequently indexes a paper under its arXiv DOI, so a lookup by the publisher
DOI that OpenAlex holds can 404. The lookup therefore falls back to a title match
and only accepts it when the normalized titles are equal.

Works without a key (shared, heavily throttled pool); set S2_API_KEY for steady use.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from .ssl_setup import ensure_system_trust

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,publicationDate,citationCount,influentialCitationCount,externalIds"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 5


class S2Error(RuntimeError):
    pass


@dataclass
class S2Paper:
    paper_id: str
    title: str | None
    publication_date: str | None
    citation_count: int | None
    influential_citation_count: int | None
    arxiv_id: str | None
    matched_by: str  # "doi" or "title"


def normalize_title(title: str | None) -> str:
    """Lowercase alphanumerics only, to compare titles across sources."""
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I) or None


def _to_paper(data: dict, matched_by: str) -> S2Paper:
    return S2Paper(
        paper_id=data.get("paperId", ""),
        title=data.get("title"),
        publication_date=data.get("publicationDate"),
        citation_count=data.get("citationCount"),
        influential_citation_count=data.get("influentialCitationCount"),
        arxiv_id=(data.get("externalIds") or {}).get("ArXiv"),
        matched_by=matched_by,
    )


class S2Client:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        ensure_system_trust()
        headers = {"User-Agent": "openalex-cli"}
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.Client(base_url=S2_BASE, timeout=timeout, headers=headers)
        # Stay near 1 request/second, the documented per-key rate.
        self._min_interval = 1.1
        self._last_call = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "S2Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def lookup(self, doi: str | None, title: str | None) -> S2Paper | None:
        """Find a paper by DOI, falling back to an exact (normalized) title match."""
        doi = bare_doi(doi)
        if doi:
            data = self._get(f"/paper/DOI:{doi}", {"fields": S2_FIELDS})
            if data:
                return _to_paper(data, "doi")
        if title:
            data = self._get(
                "/paper/search/match", {"query": title, "fields": S2_FIELDS}
            )
            hits = (data or {}).get("data") or []
            if hits and normalize_title(hits[0].get("title")) == normalize_title(title):
                return _to_paper(hits[0], "title")
        return None

    def _get(self, path: str, params: dict[str, str]) -> dict | None:
        """GET with backoff on 429/5xx. Returns None on 404 (not found)."""
        last = "no response"
        for attempt in range(MAX_RETRIES):
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self._client.get(path, params=params)
            except httpx.HTTPError as e:
                last = str(e)
                time.sleep(2**attempt)
                continue
            finally:
                self._last_call = time.monotonic()

            if resp.status_code == 404:
                return None
            if resp.status_code in RETRY_STATUS:
                last = f"HTTP {resp.status_code}"
                time.sleep(2 ** (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise S2Error(
                    f"Semantic Scholar returned {resp.status_code}: {resp.text[:200]}"
                )
            return resp.json()
        raise S2Error(f"Semantic Scholar unavailable after retries ({last}).")
