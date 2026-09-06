"""Einfacher In-Memory-Rate-Limiter für die Auth-Endpunkte (Login/Register).

Bewusst ohne externe Abhängigkeit (z.B. Redis-gestützt): reicht für den
aktuellen Single-Prozess-Betrieb. Verliert seinen Zustand bei jedem Neustart
und funktioniert nicht über mehrere Worker-Prozesse hinweg - für den
Single-Instance-Betrieb aus README/docker-compose.yml ausreichend, sollte aber
neu bewertet werden, falls die App je mit mehreren Uvicorn-Workern läuft.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_attempts: dict[str, list[float]] = defaultdict(list)


def enforce_rate_limit(*, key: str, max_attempts: int, window_seconds: float) -> None:
    now = time.monotonic()
    window_start = now - window_seconds

    attempts = [t for t in _attempts[key] if t > window_start]
    if len(attempts) >= max_attempts:
        raise HTTPException(429, "Zu viele Versuche. Bitte später erneut versuchen.")

    attempts.append(now)
    _attempts[key] = attempts


def enforce_ip_rate_limit(request: Request, *, key_prefix: str, max_attempts: int, window_seconds: float) -> None:
    client_host = request.client.host if request.client else "unknown"
    enforce_rate_limit(key=f"{key_prefix}:{client_host}", max_attempts=max_attempts, window_seconds=window_seconds)


def reset_all() -> None:
    """Nur für Tests: setzt den gesamten Rate-Limit-Zustand zurück, damit
    Tests einander nicht durch gemeinsam genutzte Zähler beeinflussen."""
    _attempts.clear()
