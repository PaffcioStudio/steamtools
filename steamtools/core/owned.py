"""
Lista WSZYSTKICH gier z konta Steam (także niezainstalowanych).

Pliki appmanifest (core/library.py) znają tylko gry zainstalowane na
dysku. Do osiągnięć i farmienia kart instalacja nie jest jednak potrzebna -
Steamworks wymaga tylko tego, żeby konto było właścicielem gry - więc
potrzebujemy listy z konta. Bez klucza Web API da się ją wziąć ze strony
profilu Steam Community, na tej samej sesji (steamLoginSecure), której
używa scraper kart:

    https://steamcommunity.com/profiles/<steamid64>/games/?tab=all

Strona osadza pełną listę jako JSON w atrybucie `data-profile-gameslist`
(klucz `rgGames`, elementy z `appid` i `name`). Starsza wersja strony
miała ją w skrypcie jako `var rgGames = [...]` - obsługujemy oba warianty.

UWAGA O KRUCHOŚCI: to scraping, jak w badges.py. Cała wiedza o strukturze
strony siedzi w parse_owned_games_html() - przy zmianie układu poprawka
zostaje w tej jednej funkcji.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from bs4 import BeautifulSoup

from steamtools.core.badges import (
    SteamCommunityError,
    SteamSessionExpiredError,
    extract_steam_id64_from_cookie,
    load_community_page,
)
from steamtools.core.config import save_debug_dump
from steamtools.core.logging_setup import get_logger

_log = get_logger("owned")

_GAMES_URL = "https://steamcommunity.com/profiles/{steam_id64}/games/?tab=all"
_XML_URL = "https://steamcommunity.com/profiles/{steam_id64}/games/?tab=all&xml=1"
_XML_GAME_RE = re.compile(
    r"<game>.*?<appID>\s*(\d+)\s*</appID>\s*<name>\s*(?:<!\[CDATA\[(.*?)\]\]>|(.*?))\s*</name>",
    re.DOTALL,
)
_RG_GAMES_RE = re.compile(r"rgGames\s*=\s*(\[.*?\])\s*;", re.DOTALL)


@dataclass
class OwnedGame:
    app_id: int
    name: str


def _games_from_list(raw_games: object) -> list[OwnedGame]:
    games: list[OwnedGame] = []
    if not isinstance(raw_games, list):
        return games
    for raw in raw_games:
        if not isinstance(raw, dict):
            continue
        app_id = raw.get("appid")
        if isinstance(app_id, str) and app_id.isdigit():
            app_id = int(app_id)
        if not isinstance(app_id, int):
            continue
        name = raw.get("name")
        games.append(
            OwnedGame(
                app_id=app_id,
                name=name.strip() if isinstance(name, str) and name.strip() else f"AppID {app_id}",
            )
        )
    return games


def parse_owned_games_html(html: str) -> list[OwnedGame] | None:
    """Wyciąga listę gier z HTML strony /games/?tab=all. Zwraca None, gdy
    nie znaleziono w niej listy w żadnym znanym formacie (zmieniony układ) -
    odróżnia to od [] czyli "lista jest, ale pusta"."""
    soup = BeautifulSoup(html, "lxml")
    holder = soup.find(attrs={"data-profile-gameslist": True})
    if holder is not None:
        try:
            data = json.loads(holder["data-profile-gameslist"])
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("rgGames"), list):
            return _games_from_list(data["rgGames"])

    match = _RG_GAMES_RE.search(html)
    if match:
        try:
            return _games_from_list(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    return None


def parse_owned_games_xml(text: str) -> list[OwnedGame] | None:
    """Starszy, stabilny endpoint XML (&xml=1). None gdy to nie jest lista
    gier (np. komunikat o prywatnym profilu)."""
    if "<gamesList" not in text:
        return None
    games = []
    for app_id, cdata, plain in _XML_GAME_RE.findall(text):
        name = (cdata or plain or "").strip()
        games.append(OwnedGame(int(app_id), name or f"AppID {app_id}"))
    return games


_TOKEN_URLS = (
    "https://steamcommunity.com/pointssummary/ajaxgetasyncconfig",
    "https://store.steampowered.com/pointssummary/ajaxgetasyncconfig",
)
_OWNED_API_URL = (
    "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?"
    "access_token={token}&steamid={steam_id64}&include_appinfo=1"
    "&include_played_free_games=1&include_free_sub=1&skip_unvetted_apps=0"
)


def _get_json(url: str, cookie_header: str = "") -> object | None:
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SteamTools/0.1.0"}
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


def _fetch_via_web_api(session_cookie: str, session_id: str, steam_id64: str) -> list[OwnedGame] | None:
    """Główna droga: na ciasteczku sesji Steam wydaje krótkotrwały token
    Web API zalogowanego użytkownika (ten sam, którego używa jego własna
    przeglądarka), a z nim IPlayerService/GetOwnedGames zwraca czysty JSON z
    nazwami - bez scrapowania HTML. None = ta droga nie zadziałała (wtedy
    próbujemy stron HTML/XML)."""
    cookie_header = f"steamLoginSecure={session_cookie}"
    if session_id:
        cookie_header += f"; sessionid={session_id}"
    for token_url in _TOKEN_URLS:
        data = _get_json(token_url, cookie_header)
        token = ""
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            token = str(data["data"].get("webapi_token") or "")
        if not token:
            continue
        url = _OWNED_API_URL.format(token=urllib.parse.quote(token), steam_id64=steam_id64)
        result = _get_json(url)
        if isinstance(result, dict) and isinstance(result.get("response"), dict):
            return _games_from_list(result["response"].get("games", []))
    return None


def fetch_owned_games(session_cookie: str, session_id: str = "") -> tuple[str, list[OwnedGame]]:
    """Zwraca (steam_id64, lista gier z konta), posortowane po nazwie, bez
    duplikatów. Kolejność prób: Web API na tokenie sesji (JSON), strona
    profilu (HTML), endpoint XML. Wyjątki: martwa sesja =
    SteamSessionExpiredError, reszta = SteamCommunityError."""
    steam_id64 = extract_steam_id64_from_cookie(session_cookie)
    if steam_id64 is None:
        raise SteamSessionExpiredError(
            "Nie udało się odczytać SteamID64 z ciasteczka steamLoginSecure - "
            "sprawdź, czy skopiowana wartość jest kompletna."
        )

    games = _fetch_via_web_api(session_cookie, session_id, steam_id64)
    source = "web_api"
    last_html = ""
    if games is None:
        source = "html"
        last_html, _ = load_community_page(_GAMES_URL, session_cookie, session_id, strict=False)
        games = parse_owned_games_html(last_html)
    if games is None:
        source = "xml"
        xml, _ = load_community_page(_XML_URL, session_cookie, session_id, strict=False)
        games = parse_owned_games_xml(xml)
        last_html = last_html or xml
    if games is None:
        _log.warning("lista gier: wszystkie źródła zawiodły")
        dump = save_debug_dump("owned_games_debug.html", last_html)
        raise SteamCommunityError(
            "Nie udało się odczytać listy gier z konta (Web API, strona "
            "profilu i XML zawiodły)."
            + (f" Surowa odpowiedź zapisana w: {dump}" if dump else "")
        )

    unique: dict[int, OwnedGame] = {}
    for game in games:
        unique.setdefault(game.app_id, game)
    _log.info("lista gier z konta: %d (źródło: %s)", len(unique), source)
    return steam_id64, sorted(unique.values(), key=lambda g: g.name.lower())
