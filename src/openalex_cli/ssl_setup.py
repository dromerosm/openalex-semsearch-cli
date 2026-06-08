"""Usa el trust store del sistema operativo en vez del bundle de certifi.

Necesario en redes corporativas con inspección TLS (p. ej. Zscaler), donde el
certificado raíz vive en el llavero del SO y no en certifi. `inject_into_ssl`
hace que httpx y el SDK de OpenAI verifiquen contra ese trust store.
"""

from __future__ import annotations

import truststore

_injected = False


def ensure_system_trust() -> None:
    """Inyecta el trust store del SO en `ssl` (idempotente)."""
    global _injected
    if not _injected:
        truststore.inject_into_ssl()
        _injected = True
