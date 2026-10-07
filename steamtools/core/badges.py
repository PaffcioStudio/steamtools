"""
Wykrywanie liczby pozostałych kart do zdobycia per gra (Etap 3 z ROADMAP).

Steamworks API (oficjalne, publiczne) NIE udostępnia tej informacji wprost
- nie ma żadnego wywołania ISteamUserStats/ISteamApps zwracającego "ile
kart drop jeszcze zostało" dla danej gry. Ta informacja istnieje tylko na
prywatnej stronie Steam Community (Badges), widocznej wyłącznie
zalogowanemu właścicielowi konta.

Dokładnie to samo ograniczenie miał idle_master_extended (patrz
CookieClient.cs w oryginalnym projekcie) - jedyny sposób to zescrapować
stronę:
    https://steamcommunity.com/id/<profil>/badges/
    https://steamcommunity.com/profiles/<steamid64>/badges/
gdzie każda gra z niewyzerowanymi dropami jest w elemencie ".badge_row",
a liczba pozostałych kart w tekście w stylu "X card drops remaining" wewnątrz
elementu z klasą "progress_info_bold".

WYMAGANA SESJA: strona badges pokazuje dropy tylko właścicielowi konta, więc
scraper potrzebuje ciasteczka sesyjnego "steamLoginSecure" - użytkownik musi
je samodzielnie skopiować z przeglądarki (DevTools -> Application/Storage ->
Cookies -> steamcommunity.com -> steamLoginSecure) i wkleić w Ustawieniach.
Trzymamy się tego ręcznego podejścia zamiast np. wbudowanej przeglądarki
(QWebEngineView) czy automatycznego logowania - to najmniej inwazyjne i
najbezpieczniejsze rozwiązanie (nie przechowujemy hasła, tylko jeden token
sesji, który user może unieważnić w dowolnej chwili wylogowując się gdzie
indziej).

UWAGA O KRUCHOŚCI: to jest scraping HTML, nie oficjalne API - jeśli Valve
zmieni strukturę strony badges, ten moduł przestanie działać i będzie
wymagał aktualizacji selektorów. Stąd wszystkie założenia o strukturze HTML
są odizolowane w jednej funkcji (_parse_badges_html), żeby ewentualną
naprawę ograniczyć do jednego miejsca.
"""

from __future__ import annotations

import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup


class SteamCommunityError(RuntimeError):
    """Ogólny błąd komunikacji ze Steam Community (brak sieci, throttling,
    nierozpoznana strona itp.). NIE oznacza jeszcze, że sesja jest martwa -
    do tego służy podklasa SteamSessionExpiredError."""


class SteamSessionExpiredError(SteamCommunityError):
    """Steam POTWIERDZIŁ, że podane steamLoginSecure nie loguje (wygasło,
    zostało unieważnione albo ma zły format). Tylko ten wyjątek uprawnia UI
    do twierdzenia "sesja wygasła" - przy zwykłym braku internetu czy
    błędzie 5xx rzucamy SteamCommunityError, żeby nie straszyć usera (i nie
    kasować mu ważnego ciasteczka) z powodu chwilowych problemów sieci."""


@dataclass
class SessionInfo:
    """Wynik udanej weryfikacji sesji: do kogo należy ciasteczko."""

    steam_id64: str
    persona_name: Optional[str] = None


@dataclass
class BadgeProgress:
    app_id: int
    name: str
    cards_remaining: int


# --------------------------------------------------------------------- #
# Cache wyniku ostatniego scrapowania, współdzielony między WSZYSTKIMI
# widokami (IdleView, LibraryView, ...). Bez tego każdy widok trzymał
# własną kopię wyniku w swoim modelu/atrybucie instancji, więc sprawdzenie
# kart w jednej zakładce (np. Farm kart) nie było w ogóle widoczne w
# drugiej (Biblioteka dalej pokazywała "Brak danych o kartach") - trzeba
# było klikać "Sprawdź" osobno w każdym miejscu, mimo że to dokładnie to
# samo zapytanie do tej samej strony Steam Community.
#
# To jest zwykły moduł-poziom stan (nie plik na dysku) - żyje tylko przez
# czas działania aplikacji, resetuje się przy restarcie, co jest w
# porządku: to tylko cache ostatniego sprawdzenia w tej sesji, nie trwałe
# dane użytkownika.
# --------------------------------------------------------------------- #

_cached_results: Optional[list[BadgeProgress]] = None
_cached_at: Optional[float] = None


def get_cached_badge_progress() -> Optional[list[BadgeProgress]]:
    """Zwraca wynik ostatniego udanego sprawdzenia kart w tej sesji
    aplikacji, niezależnie z którego widoku zostało zainicjowane. `None`
    oznacza, że jeszcze nic nie sprawdzano od uruchomienia aplikacji."""
    return _cached_results


def get_cached_badge_progress_age_seconds() -> Optional[float]:
    """Ile sekund temu wykonano ostatnie udane sprawdzenie - `None` jeśli
    jeszcze nie sprawdzano. Widoki mogą to użyć np. do pokazania "ostatnio
    sprawdzono X min temu" zamiast suchego braku informacji."""
    if _cached_at is None:
        return None
    return time.time() - _cached_at


def set_cached_badge_progress(results: list[BadgeProgress]) -> None:
    """Zapisuje świeży wynik scrapowania do współdzielonego cache - wołane
    przez KAŻDY widok po udanym sprawdzeniu, żeby pozostałe widoki mogły z
    niego skorzystać bez ponownego zapytania do Steam Community."""
    global _cached_results, _cached_at
    _cached_results = list(results)
    _cached_at = time.time()


def format_cards_count(count: int) -> str:
    """Formatuje liczbę pozostałych kart z poprawną polską odmianą
    liczebnika (karta/karty/kart) - używane zarówno w IdleView jak i
    LibraryView, żeby nie duplikować tej samej logiki w dwóch miejscach."""
    if count == 0:
        return "Brak kart"
    if count == 1:
        return "1 karta"
    last_digit = count % 10
    last_two_digits = count % 100
    if 2 <= last_digit <= 4 and not (12 <= last_two_digits <= 14):
        return f"{count} karty"
    return f"{count} kart"


def extract_steam_id64_from_cookie(session_cookie: str) -> Optional[str]:
    """Wyciąga SteamID64 wprost z wartości ciasteczka steamLoginSecure -
    NIE trzeba go osobno podawać. Format tego ciasteczka (udokumentowany
    przez community, m.in. dev.doctormckay.com/topic/365-cookies) to:

        <SteamID64>||<40-znakowy token hex>

    zapisane w przeglądarce jako URL-encoded (|| jako %7C%7C). Zwraca None,
    jeśli format się nie zgadza (np. user wkleił coś zupełnie innego) -
    wtedy trzeba poprosić o ręczne uzupełnienie albo zgłosić błąd.
    """
    import urllib.parse

    decoded = urllib.parse.unquote(session_cookie)
    # Akceptujemy zarówno "||" (już zdekodowane) jak i surowe "%7C%7C" na
    # wypadek gdyby user wkleił wartość bez URL-decode (niektóre przeglądarki
    # w DevTools pokazują ciasteczko już zdekodowane, inne nie).
    separator = "||" if "||" in decoded else None
    if separator is None:
        return None

    steam_id_part = decoded.split(separator, 1)[0]
    if steam_id_part.isdigit() and len(steam_id_part) == 17:
        return steam_id_part
    return None


_LOGGED_IN_ID_RE = re.compile(r"""g_steamID\s*=\s*["']?(\d{17})["']?""")
_LOGGED_OUT_RE = re.compile(r"""g_steamID\s*=\s*(?:false|null|["']{2})""")


def _detect_login_state(html: str) -> Optional[bool]:
    """Rozpoznaje po HTML-u, czy Steam widzi nas jako ZALOGOWANYCH.

    To jest sedno weryfikacji sesji. Samo to, że strona zawiera
    `g_rgProfileData` albo `badge_row`, NIC nie dowodzi - te elementy są też
    na publicznej stronie profilu oglądanej bez logowania (wtedy Steam po
    prostu nie pokazuje dropów, które widzi tylko właściciel konta, i
    scraper zwracał pustą listę, wyglądającą jak "brak kart").

    Wiarygodne sygnały (nagłówek każdej strony Steam Community):
      - zalogowany:    `g_steamID = "7656..."` oraz rozwijane menu konta
                       `#account_pulldown` z nazwą użytkownika,
      - niezalogowany: `g_steamID = false` oraz link do /login/.

    Zwraca True/False, a None gdy nie widać żadnego z sygnałów (np. strona
    konserwacyjna Steam albo zmiana układu) - wtedy NIE twierdzimy, że
    sesja wygasła.
    """
    if _LOGGED_IN_ID_RE.search(html) or 'id="account_pulldown"' in html:
        return True
    if _LOGGED_OUT_RE.search(html):
        return False
    if "/login/home" in html or "global_action_link" in html:
        return False
    return None


def _extract_persona_name(html: str) -> Optional[str]:
    """Nazwa użytkownika z nagłówka strony - kilka selektorów po kolei, bo
    to czysto kosmetyczna informacja (potwierdza userowi, że jest
    zalogowany na właściwe konto); jej brak nie unieważnia sesji."""
    soup = BeautifulSoup(html, "lxml")
    for selector in (
        "#account_pulldown",
        ".profile_small_header_name a",
        ".actual_persona_name",
    ):
        el = soup.select_one(selector)
        if el is not None:
            text = el.get_text(strip=True)
            if text:
                return text
    return None


def load_community_page(
    url: str, session_cookie: str, session_id: str = "", strict: bool = True
) -> tuple[str, SessionInfo]:
    """Pobiera dowolną stronę Steam Community na ciasteczku sesji i
    WERYFIKUJE, że Steam uznaje nas za zalogowanych. Jedyne miejsce w
    programie, które robi takie zapytanie - scraping kart, lista gier z
    konta i sprawdzanie sesji w zakładce Konto / przy starcie idą tą samą
    drogą, więc nie da się już "sprawdzić" czegokolwiek na martwym
    ciasteczku i dostać pustego, mylącego wyniku.

    Rzuca:
      SteamSessionExpiredError - Steam potwierdził brak zalogowania
                                 (albo ciasteczko ma zły format),
      SteamCommunityError      - problem sieci/Steam, sesji nie dało się
                                 ocenić (to NIE znaczy, że wygasła).
    """
    steam_id64 = extract_steam_id64_from_cookie(session_cookie)
    if steam_id64 is None:
        raise SteamSessionExpiredError(
            "Nie udało się odczytać SteamID64 z ciasteczka steamLoginSecure - "
            "sprawdź, czy skopiowana wartość jest kompletna (format to "
            "<SteamID64>||<token>, np. 76561198012345678||A1B2C3...)."
        )

    cookie_header = f"steamLoginSecure={session_cookie}"
    if session_id:
        cookie_header += f"; sessionid={session_id}"

    request = urllib.request.Request(
        url.format(steam_id64=steam_id64),
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SteamTools/0.1.0",
            "Cookie": cookie_header,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SteamSessionExpiredError(
                f"Steam odrzucił ciasteczko (HTTP {exc.code})."
            ) from exc
        if exc.code == 429:
            raise SteamCommunityError(
                "Steam tymczasowo ogranicza liczbę zapytań (HTTP 429) - "
                "spróbuj ponownie za kilka minut."
            ) from exc
        raise SteamCommunityError(
            f"Steam Community zwróciło błąd HTTP {exc.code} - "
            f"spróbuj ponownie za chwilę."
        ) from exc
    except urllib.error.URLError as exc:
        raise SteamCommunityError(
            f"Brak połączenia ze Steam Community: {exc.reason}"
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise SteamCommunityError(f"Brak połączenia ze Steam Community: {exc}") from exc

    # strict=False dla stron o innym układzie nagłówka niż Badges (nowsze
    # strony Steam nie zawsze mają g_steamID/account_pulldown): sesję uznajemy
    # za martwą tylko po wyraźnym sygnale wylogowania, a brak sygnałów nie
    # jest błędem - o poprawności odpowiedzi decyduje wtedy sam parser strony.
    if strict:
        logged_in = _detect_login_state(html)
    else:
        logged_in = False if _LOGGED_OUT_RE.search(html) else True
    if logged_in is False:
        raise SteamSessionExpiredError(
            "Steam nie rozpoznaje tego ciasteczka jako zalogowanej sesji "
            "(wygasło albo zostało unieważnione)."
        )
    if logged_in is None:
        raise SteamCommunityError(
            "Nie rozpoznano odpowiedzi Steam Community (strona konserwacyjna "
            "albo zmieniony układ strony) - nie da się ocenić, czy sesja "
            "jest ważna. Spróbuj ponownie później."
        )

    return html, SessionInfo(steam_id64=steam_id64, persona_name=_extract_persona_name(html))


def _load_badges_page(session_cookie: str, session_id: str = "") -> tuple[str, SessionInfo]:
    return load_community_page(
        "https://steamcommunity.com/profiles/{steam_id64}/badges/?p=1",
        session_cookie,
        session_id,
    )


def verify_session(session_cookie: str, session_id: str = "") -> SessionInfo:
    """Sprawdza, czy ciasteczko steamLoginSecure FAKTYCZNIE loguje, i zwraca
    SteamID64 oraz nazwę użytkownika (do pokazania w zakładce Konto).
    Wyjątki jak w _load_badges_page."""
    _html, info = _load_badges_page(session_cookie, session_id)
    return info


def fetch_badge_progress(session_cookie: str, session_id: str = "") -> list[BadgeProgress]:
    """Pobiera i parsuje stronę Badges dla konta powiązanego z podanym
    ciasteczkiem sesji (wszystkie gry z niewyzerowanymi dropami na raz -
    jedno zapytanie HTTP zamiast N zapytań per gra, zgodnie z tym jak
    robił to oryginalny idle_master_extended).

    `session_cookie` to wartość ciasteczka "steamLoginSecure" skopiowana
    przez użytkownika z przeglądarki po zalogowaniu na steamcommunity.com -
    SteamID64 jest z niego wyciągane automatycznie (patrz
    extract_steam_id64_from_cookie), user NIE musi go podawać osobno.

    `session_id` to opcjonalna wartość ciasteczka "sessionid" (24-znakowy
    hex token CSRF) - puste zwykle wystarcza do samego odczytu strony
    Badges (GET, nie POST).

    Gdy sesja jest martwa, rzuca SteamSessionExpiredError ZAMIAST zwracać
    pustą listę - pusta lista oznacza wyłącznie "zalogowany, ale żadna gra
    nie ma już dropów".

    Strona Badges jest stronicowana (p=1, p=2, ...) - pobieramy tylko
    pierwszą stronę. Dociągnięcie kolejnych zostawione jako rozszerzenie.
    """
    html, _info = _load_badges_page(session_cookie, session_id)
    return _parse_badges_html(html)


def _parse_badges_html(html: str) -> list[BadgeProgress]:
    """Wyciąga listę (app_id, nazwa, pozostałe karty) z HTML strony Badges.

    Cała wiedza o strukturze strony Steam Community jest odizolowana w tej
    jednej funkcji - jeśli Valve zmieni HTML, to tu (i tylko tu) trzeba
    będzie poprawić selektory.
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[BadgeProgress] = []

    for row in soup.select(".badge_row"):
        progress_text_el = row.select_one(".badge_title_stats_content .progress_info_bold")
        if progress_text_el is None:
            continue  # ta gra nie ma sekcji postępu - brak dropów do pokazania

        match = re.search(r"(\d+)", progress_text_el.get_text())
        if not match:
            continue
        cards_remaining = int(match.group(1))
        if cards_remaining <= 0:
            continue  # "0 card drops remaining" / brak liczby - pomijamy

        # AppID jest zwykle zakodowany w linku do strony gry wewnątrz wiersza
        # badge'a, np. href="https://steamcommunity.com/my/gamecards/251570/"
        link_el = row.select_one("a.badge_row_overlay")
        app_id = None
        if link_el is not None and link_el.has_attr("href"):
            id_match = re.search(r"/gamecards/(\d+)", link_el["href"])
            if id_match:
                app_id = int(id_match.group(1))

        if app_id is None:
            continue  # nie udało się ustalić AppID - pomijamy wpis

        title_el = row.select_one(".badge_title")
        name = title_el.get_text(strip=True) if title_el else f"AppID {app_id}"
        # Steam dokleja do tytułu badge'a tekst ukrytego linku "View
        # details" bez spacji przed nim (np. "Builder SimulatorView
        # details", "TerrariaView details") - .get_text() łączy to z
        # właściwą nazwą gry w jeden ciąg. Usuwamy to, żeby nazwa gry była
        # czysta zamiast "Builder SimulatorView details".
        name = re.sub(r"View details\s*$", "", name).strip()

        results.append(BadgeProgress(app_id=app_id, name=name, cards_remaining=cards_remaining))

    return results
