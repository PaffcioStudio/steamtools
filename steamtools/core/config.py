"""
Persystencja stanu aplikacji między uruchomieniami - na razie tylko
kolejka farmienia kart (Etap 3 z ROADMAP), ale zaprojektowane tak, żeby
dało się łatwo dopisać kolejne sekcje (np. ustawienia z settings_view.py)
bez zmiany formatu pliku.

Plik trzymany w standardowej lokalizacji XDG (~/.config/steamtools/), nie
w katalogu projektu - to jest stan użytkownika, nie część repo/kodu.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _config_dir() -> Path:
    """Zwraca katalog konfiguracyjny zgodny z XDG Base Directory - jeśli
    XDG_CONFIG_HOME jest ustawione (rzadkie, ale spotykane w niestandardowych
    konfiguracjach), używamy go zamiast domyślnego ~/.config."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "steamtools"


def _project_root() -> Path:
    """Katalog, względem którego szukamy plików repo (VERSION, ROADMAP.md)
    - NIE ~/.config, bo te pliki są częścią kodu/repo, nie stanu usera.
    Dwie różne bazy zależnie od trybu uruchomienia:
    - PyInstaller --onedir (patrz packaging/steamtools.spec): pliki z
      `datas=[...]` lądują obok binarki, ścieżka do nich to sys._MEIPASS
      (ustawiane przez sam PyInstaller w runtime, nie ma go przy zwykłym
      `python -m steamtools.app`).
    - Uruchomienie z kodu źródłowego (./run.sh, `python -m steamtools.app`):
      ten plik siedzi w steamtools/core/config.py, więc korzeń repo jest
      dwa poziomy wyżej."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent.parent


def get_app_version() -> str:
    """Wersja aplikacji z pliku VERSION w korzeniu repo - JEDYNE źródło
    prawdy, żeby uniknąć dokładnie tego, co działo się wcześniej: build.sh
    przyjmował numer wersji jako argument (do nazwy paczki .deb/AppImage),
    ale sam kod Pythona (ui/views/about_view.py) miał wersję wpisaną na
    sztywno osobnym literałem - zakładka Informacje pokazywała "0.1.0"
    nawet gdy paczka nazywała się "steamtools_0.1.2_amd64.deb". Teraz
    zarówno build.sh/build_deb.sh (przez `cat VERSION`), jak i ten kod w
    runtime, czytają dokładnie ten sam plik.
    "dev" jako fallback (plik nie istnieje/nie do odczytu) zamiast
    wyjątku - lepiej pokazać coś niż wywalić całą zakładkę Informacje
    z powodu brakującego pliku wersji."""
    version_file = _project_root() / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def _idle_queue_path() -> Path:
    return _config_dir() / "idle_queue.json"


def settings_file_path() -> Path:
    """Ścieżka pliku ustawień UI (motyw, tray, powiadomienia itd.),
    zarządzanego przez QConfig z qfluentwidgets (ui/views/settings_view.py:
    AppConfig). Osobna funkcja zamiast literału w settings_view.py, żeby
    cała logika lokalizacji plików stanu aplikacji siedziała w jednym
    miejscu (ten moduł), spójnie z idle_queue.json i community_session.json
    poniżej."""
    return _config_dir() / "settings.json"


@dataclass
class SavedIdleEntry:
    app_id: int
    name: str
    was_paused: bool = False


@dataclass
class IdleQueueState:
    entries: list[SavedIdleEntry] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "entries": [
                    {"app_id": e.app_id, "name": e.name, "was_paused": e.was_paused}
                    for e in self.entries
                ]
            },
            indent=2,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, text: str) -> "IdleQueueState":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return cls()

        entries = []
        for raw in data.get("entries", []):
            app_id = raw.get("app_id")
            name = raw.get("name")
            if isinstance(app_id, int) and isinstance(name, str):
                entries.append(
                    SavedIdleEntry(
                        app_id=app_id,
                        name=name,
                        was_paused=bool(raw.get("was_paused", False)),
                    )
                )
        return cls(entries=entries)


def save_idle_queue(state: IdleQueueState) -> None:
    """Zapisuje kolejkę idle do pliku. Best-effort - błąd zapisu (np. brak
    uprawnień do ~/.config) nie powinien wywalać aplikacji, tylko zostać
    po cichu zignorowany (ryzykujemy co najwyżej utratę persystencji, nie
    utratę funkcjonalności w bieżącej sesji)."""
    try:
        config_dir = _config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        _idle_queue_path().write_text(state.to_json(), encoding="utf-8")
    except OSError:
        pass


def load_idle_queue() -> IdleQueueState:
    """Wczytuje zapisaną kolejkę idle. Zwraca pusty stan, jeśli plik nie
    istnieje, jest uszkodzony, lub nie da się go odczytać - w każdym z tych
    przypadków aplikacja powinna po prostu wystartować z pustą kolejką,
    nie wywalać się z błędem."""
    path = _idle_queue_path()
    if not path.exists():
        return IdleQueueState()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return IdleQueueState()
    return IdleQueueState.from_json(text)


def clear_idle_queue() -> None:
    """Usuwa zapisaną kolejkę - wywoływane po tym jak user świadomie
    zdecyduje się NIE wznawiać zapisanej kolejki przy starcie, żeby przy
    kolejnym uruchomieniu nie pytać go znowu o tę samą, odrzuconą kolejkę."""
    try:
        _idle_queue_path().unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------- #
# Dane sesji Steam Community (cookie do scrapowania strony Badges -
# core/badges.py). To są dane WRAŻLIWE (token sesji daje dostęp do konta
# Steam Community w zakresie zbliżonym do bycia zalogowanym w przeglądarce),
# więc trzymamy je w OSOBNYM pliku od reszty configu, z restrykcyjnymi
# uprawnieniami (0600 - tylko właściciel może czytać/pisać), zamiast w
# ogólnym QConfig (który qfluentwidgets zapisuje jako zwykły, czytelny dla
# innych procesów na koncie plik JSON).
# ---------------------------------------------------------------------- #


def _community_session_path() -> Path:
    return _config_dir() / "community_session.json"


@dataclass
class CommunitySession:
    session_cookie: str = ""
    session_id: str = ""

    def is_configured(self) -> bool:
        # SteamID64 NIE jest tu polem - wyliczane automatycznie z
        # session_cookie (patrz core/badges.py: extract_steam_id64_from_cookie).
        # session_id (CSRF token) jest opcjonalny - część zapytań do Steam
        # Community go nie wymaga, więc nie blokujemy konfiguracji jego brakiem.
        return bool(self.session_cookie)


def save_community_session(session: CommunitySession) -> None:
    """Zapisuje dane sesji z uprawnieniami 0600 (tylko właściciel pliku
    może go odczytać) - best-effort, jak w save_idle_queue."""
    try:
        config_dir = _config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        path = _community_session_path()
        data = json.dumps(
            {"session_cookie": session.session_cookie, "session_id": session.session_id},
            indent=2,
        )
        path.write_text(data, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_community_session() -> CommunitySession:
    path = _community_session_path()
    if not path.exists():
        return CommunitySession()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CommunitySession()
    return CommunitySession(
        session_cookie=str(data.get("session_cookie", "")),
        session_id=str(data.get("session_id", "")),
    )


def clear_community_session() -> None:
    try:
        _community_session_path().unlink(missing_ok=True)
    except OSError:
        pass
