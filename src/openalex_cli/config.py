"""Configuration loading from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openalex_api_key: str | None
    openai_api_key: str | None
    # Email for OpenAlex's "polite pool" (optional but recommended).
    mailto: str | None
    openai_embed_model: str
    # Chat model to describe clusters from the abstracts.
    openai_describe_model: str
    # Semantic Scholar key (optional): steadier limits for `citations --s2`.
    s2_api_key: str | None = None

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    """Read .env from the current directory (and the environment) once."""
    load_dotenv()
    return Settings(
        openalex_api_key=os.getenv("OPENALEX_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        mailto=os.getenv("OPENALEX_MAILTO") or os.getenv("MAILTO"),
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        openai_describe_model=os.getenv("OPENAI_DESCRIBE_MODEL", "gpt-5.4-mini"),
        s2_api_key=os.getenv("S2_API_KEY") or os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
    )
