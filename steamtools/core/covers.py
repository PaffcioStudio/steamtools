"""
Okładki gier do Biblioteki.

Kolejność źródeł dla jednego AppID:
  1. cache klienta Steam (`appcache/librarycache`) - działa offline i nic nie
     kosztuje; obsługujemy oba układy katalogów, bo klient Steam zmieniał go
     w czasie (płaskie pliki `<appid>_header.jpg` oraz podkatalogi
     `<appid>/<hash>/header.jpg`),
  2. własny cache na dysku (`~/.config/steamtools/covers/<appid>.jpg`),
  3. Steam CDN (`header.jpg` gry) - zapisywane do własnego cache.
Zwracany jest surowy QImage; skalowanie i rysowanie robi widok.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from PyQt6.QtGui import QImage

from steamtools.core.config import covers_cache_dir
from steamtools.core.library import _default_steam_paths

_CDN_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
_HEADER_NAMES = ("header.jpg", "library_header.jpg")
_MAX_BYTES = 2 * 1024 * 1024


def find_local_cover(app_id: int) -> Path | None:
    """Okładka z cache klienta Steam albo None."""
    for steam in _default_steam_paths():
        cache = steam / "appcache" / "librarycache"
        if not cache.is_dir():
            continue
        flat = cache / f"{app_id}_header.jpg"
        if flat.is_file():
            return flat
        folder = cache / str(app_id)
        if folder.is_dir():
            for name in _HEADER_NAMES:
                found = next(folder.rglob(name), None)
                if found is not None:
                    return found
    return None


def _download(app_id: int) -> bytes | None:
    request = urllib.request.Request(
        _CDN_URL.format(app_id=app_id),
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SteamTools/0.1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    return data if 0 < len(data) <= _MAX_BYTES else None


def load_cover(app_id: int) -> QImage | None:
    """Zwraca okładkę gry (z dowolnego źródła) albo None. Blokuje na czas
    ewentualnego pobierania - wołać z wątku roboczego, nie z GUI."""
    local = find_local_cover(app_id)
    if local is not None:
        image = QImage(str(local))
        if not image.isNull():
            return image

    cached = covers_cache_dir() / f"{app_id}.jpg"
    if cached.is_file():
        image = QImage(str(cached))
        if not image.isNull():
            return image

    data = _download(app_id)
    if data is None:
        return None
    image = QImage()
    if not image.loadFromData(data):
        return None
    try:
        covers_cache_dir().mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass  # brak zapisu to tylko utrata cache, okładka i tak się pokaże
    return image
