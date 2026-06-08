"""Carga de configuración desde el .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openalex_api_key: str | None
    openai_api_key: str | None
    # Email para el "polite pool" de OpenAlex (opcional pero recomendado).
    mailto: str | None
    openai_embed_model: str
    # Modelo de chat para describir clusters a partir de los abstracts.
    openai_describe_model: str

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    """Lee el .env del directorio actual (y del entorno) una sola vez."""
    load_dotenv()
    return Settings(
        openalex_api_key=os.getenv("OPENALEX_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        mailto=os.getenv("OPENALEX_MAILTO") or os.getenv("MAILTO"),
        openai_embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        openai_describe_model=os.getenv("OPENAI_DESCRIBE_MODEL", "gpt-5.4-mini"),
    )
