"""
Logi do pliku: ~/.local/share/steamtools/logs/steamtools.log (XDG_DATA_HOME).

Przydatne, gdy coś nie działa i terminal nie był otwarty: nieobsłużone
wyjątki (także z wątków) oraz kluczowe zdarzenia (błędy Steamworks,
pobierania listy gier, wygasanie sesji) trafiają do pliku z rotacją
(3 x 1 MB). STEAMTOOLS_DEBUG=1 włącza też poziom DEBUG.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOGGER_NAME = "steamtools"


def log_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "steamtools" / "logs"


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging(version: str = "") -> Path | None:
    """Konfiguruje logowanie do pliku i hooki na nieobsłużone wyjątki.
    Zwraca ścieżkę pliku logu albo None, gdy nie da się go utworzyć (wtedy
    aplikacja działa dalej, logując tylko ostrzeżenia na stderr)."""
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_steamtools_configured", False):
        return None
    logger.setLevel(logging.DEBUG if os.environ.get("STEAMTOOLS_DEBUG") else logging.INFO)
    logger.propagate = False

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(stderr_handler)

    path: Path | None = None
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "steamtools.log"
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError:
        path = None

    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        logger.critical("Nieobsłużony wyjątek", exc_info=(exc_type, exc, tb))
        previous_hook(exc_type, exc, tb)

    def _thread_hook(args):
        logger.critical(
            "Nieobsłużony wyjątek w wątku %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook

    logger._steamtools_configured = True  # type: ignore[attr-defined]
    logger.info("Start SteamTools %s (Python %s)", version or "?", sys.version.split()[0])
    return path
