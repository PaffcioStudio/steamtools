"""
Odczyt biblioteki gier lokalnego użytkownika Steam.

SAM.Picker (C#) robi to przez zapytania do lokalnego Steam clienta via
Steamworks (ISteamApps). My idziemy prostszą, bardziej niezawodną drogą
używaną przez większość narzędzi community (ASF, SLPS itd.): parsujemy
pliki `appmanifest_<appid>.acf` w katalogach `steamapps/` oraz
`libraryfolders.vdf` - są to zwykłe pliki w formacie VDF (Valve Data
Format), czytelne bez żadnego SDK i bez konieczności, aby klient Steam był
akurat uruchomiony.

Dla card-idlingu i achievementów wciąż potrzebny jest *uruchomiony* klient
Steam (Steamworks tego wymaga), ale samo "jakie gry posiadam / mam
zainstalowane" można ustalić offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

VdfDict = dict[str, Union[str, "VdfDict"]]


@dataclass
class InstalledGame:
    app_id: int
    name: str
    install_dir: str
    library_path: Path
    size_on_disk: int = 0


# ---------------------------------------------------------------------- #
# Filtrowanie narzędzi systemowych Steam (nie są "grami")
# ---------------------------------------------------------------------- #
#
# Steam instaluje szereg pomocniczych "aplikacji" jako zwykłe appmanifest -
# runtime'y kompatybilności, redystrybuowalne biblioteki itd. Mają swoje
# AppID i pojawiają się w steamapps/ tak samo jak prawdziwe gry, ale user
# nigdy nie chce ich widzieć w bibliotece do farmienia/osiągnięć (nie mają
# ani jednego, ani drugiego).
#
# Lista AppID jest stała i utrzymywana przez Valve - filtrowanie po ID jest
# pewniejsze niż po nazwie (nazwy bywają lokalizowane/zmieniane). Zawiera
# tylko pozycje o powszechnie znanych, stabilnych AppID (runtime'y
# kompatybilności Steam) - różne wersje/warianty Protona mają zbyt
# niepewne/zmieniające się numery, więc te łapiemy niżej przez wzorzec nazwy.
_EXCLUDED_APP_IDS: frozenset[int] = frozenset({
    1391110,  # Steam Linux Runtime 1.0 (scout)
    1628350,  # Steam Linux Runtime 2.0 (soldier)
    1493710,  # Steam Linux Runtime 3.0 (sniper)
    1070560,  # Steam Linux Runtime 4.0
    228980,   # Steamworks Common Redistributables
})

# Fallback po nazwie/wzorcu - łapie Proton (wszystkie wersje) oraz nowe
# runtime'y, których AppID mogą się zmienić w przyszłości, bez potrzeby
# aktualizacji listy wyżej. To główny mechanizm filtrujący dla Protona,
# bo Valve wypuszcza nowe wersje z nowymi AppID regularnie.
_EXCLUDED_NAME_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^Steam Linux Runtime", re.IGNORECASE),
    re.compile(r"^Proton\b", re.IGNORECASE),
    re.compile(r"^Steamworks Common Redistributables$", re.IGNORECASE),
    re.compile(r"^SteamVR$", re.IGNORECASE),
)


def _is_steam_tool(app_id: int, name: str) -> bool:
    if app_id in _EXCLUDED_APP_IDS:
        return True
    return any(pattern.match(name) for pattern in _EXCLUDED_NAME_PATTERNS)


# ---------------------------------------------------------------------- #
# Parser VDF (Valve Data Format / KeyValues)
# ---------------------------------------------------------------------- #
#
# Format wygląda tak (patrz przykłady appmanifest_*.acf i
# libraryfolders.vdf), z dowolnym poziomem zagnieżdżenia:
#
#   "KluczGlowny"
#   {
#       "prostyKlucz"       "wartosc"
#       "sekcja"
#       {
#           "0"     "wartosc0"
#           "1"     "wartosc1"
#       }
#   }
#
# Poprzedni parser (regex łapiący WSZYSTKIE pary "klucz" "wartość" płasko,
# bez śledzenia zagnieżdżenia) rozjeżdżał się na libraryfolders.vdf, bo tam
# klucze typu "path" powtarzają się w każdej z ponumerowanych sekcji ("0",
# "1", "2"...) - płaski parser nadpisywał wartości i tracił informację
# które "apps" należą do której biblioteki.
#
# Ten parser buduje właściwe, zagnieżdżone drzewo przez tokenizację +
# rekurencyjne zejście, więc struktura jest zachowana 1:1.

_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|(\{)|(\})')


def _tokenize(text: str) -> list[str]:
    """Zwraca listę tokenów: cudzysłowowe stringi (już odescape'owane),
    oraz pojedyncze znaki '{' i '}'. Komentarze VDF (linie zaczynające się
    od //) są pomijane."""
    tokens: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for match in _TOKEN_RE.finditer(line):
            quoted, open_brace, close_brace = match.groups()
            if quoted is not None:
                tokens.append(quoted.replace('\\"', '"').replace("\\\\", "\\"))
            elif open_brace:
                tokens.append("{")
            elif close_brace:
                tokens.append("}")
    return tokens


def parse_vdf(text: str) -> VdfDict:
    """Parsuje tekst VDF do zagnieżdżonego słownika. Zwraca zawartość
    najbardziej zewnętrznego bloku (bez nazwy klucza głównego), analogicznie
    do tego jak robi to popularny pakiet `vdf` z PyPI (`vdf.loads`), ale bez
    dodatkowej zależności.

    Przy zduplikowanych kluczach na tym samym poziomie (VDF na to pozwala,
    Steam z tego korzysta rzadko) - ostatnia wartość wygrywa, spójnie z tym
    jak Valve sam to interpretuje w oficjalnych narzędziach.
    """
    tokens = _tokenize(text)
    pos = 0

    def parse_block() -> VdfDict:
        nonlocal pos
        result: VdfDict = {}
        while pos < len(tokens):
            token = tokens[pos]
            if token == "}":
                pos += 1
                return result
            # token to klucz (string)
            key = token
            pos += 1
            if pos >= len(tokens):
                break
            next_token = tokens[pos]
            if next_token == "{":
                pos += 1
                result[key] = parse_block()
            else:
                # wartość to zwykły string
                result[key] = next_token
                pos += 1
        return result

    if not tokens:
        return {}

    # Najbardziej zewnętrzny poziom to zwykle: "NazwaKlucza" { ...zawartość... }
    # Chcemy zawartość, nie sam wrapper - stąd specjalna obsługa pierwszego wpisu.
    if tokens[0] != "{" and len(tokens) > 1 and tokens[1] == "{":
        pos = 2
        return parse_block()

    # Fallback: plik zaczyna się od razu blokiem, albo ma nietypowy kształt.
    pos = 0
    return parse_block()


def _as_dict(value) -> VdfDict:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------- #
# Wykrywanie instalacji Steam i bibliotek
# ---------------------------------------------------------------------- #


def _default_steam_paths() -> list[Path]:
    """Typowe lokalizacje instalacji Steam na Linuksie (natywny pakiet,
    Flatpak, Snap). Obejmuje też `~/.steam/debian-installation`, używaną
    przez pakiet .deb Steama na Debianie/Ubuntu/pochodnych (w tym TuxedoOS)
    - to bywa inny katalog niż klasyczny `~/.steam/steam` symlink."""
    home = Path.home()
    candidates = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".steam/debian-installation",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",  # Flatpak
        home / "snap/steam/common/.local/share/Steam",  # Snap
    ]
    return [p for p in candidates if p.exists()]


def find_library_folders() -> list[Path]:
    """Zwraca ścieżki do wszystkich katalogów steamapps: głównej instalacji
    Steam oraz wszystkich dodatkowych bibliotek (inne dyski/partycje)
    zdefiniowanych w libraryfolders.vdf.

    libraryfolders.vdf ma strukturę:
        "libraryfolders"
        {
            "0" { "path" "/home/user/.steam/debian-installation" ... "apps" {...} }
            "1" { "path" "/media/user/Dysk/SteamLibrary" ... "apps" {...} }
            ...
        }
    Sekcje są numerowane jako klucze "0", "1", "2"... (kolejność wpisu, nie
    zawsze pokrywa się z kolejnością na dysku) - iterujemy po wszystkich
    wartościach niezależnie od konkretnych nazw kluczy, żeby nie zakładać
    ile bibliotek user ma skonfigurowanych.
    """
    folders: list[Path] = []

    for steam_path in _default_steam_paths():
        main_steamapps = steam_path / "steamapps"
        if main_steamapps.exists():
            folders.append(main_steamapps)

        vdf_path = main_steamapps / "libraryfolders.vdf"
        if not vdf_path.exists():
            continue

        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
        data = parse_vdf(text)

        for entry in data.values():
            entry_dict = _as_dict(entry)
            raw_path = entry_dict.get("path")
            if not isinstance(raw_path, str):
                continue
            candidate = Path(raw_path) / "steamapps"
            if candidate.exists():
                folders.append(candidate)

    # Usuń duplikaty zachowując kolejność (ta sama biblioteka może zostać
    # znaleziona zarówno jako "główna" jak i wpis w libraryfolders.vdf).
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in folders:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)
    return unique


def scan_installed_games() -> list[InstalledGame]:
    """Skanuje wszystkie appmanifest_*.acf we wszystkich znalezionych
    bibliotekach i zwraca listę zainstalowanych gier.

    Pomija pliki tymczasowe w trakcie pobierania/weryfikacji, np.:
        appmanifest_1631270.acf.2728035087.tmp
    Steam tworzy je podczas aktualizacji i mają losowy numeryczny suffix po
    ".acf" - dopasowanie glob `appmanifest_*.acf` samo w sobie by je złapało,
    więc odfiltrowujemy jawnie po dokładnym wzorcu nazwy pliku.
    """
    games: list[InstalledGame] = []
    manifest_pattern = re.compile(r"^appmanifest_\d+\.acf$")

    for steamapps in find_library_folders():
        for manifest in steamapps.glob("appmanifest_*.acf"):
            if not manifest_pattern.match(manifest.name):
                continue  # np. plik .tmp w trakcie aktualizacji - pomiń

            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            data = parse_vdf(text)
            app_id = data.get("appid")
            name = data.get("name")
            install_dir = data.get("installdir", "")
            size_raw = data.get("SizeOnDisk", "0")

            if isinstance(app_id, str) and isinstance(name, str) and app_id.isdigit():
                app_id_int = int(app_id)
                if _is_steam_tool(app_id_int, name):
                    continue
                games.append(
                    InstalledGame(
                        app_id=app_id_int,
                        name=name,
                        install_dir=install_dir if isinstance(install_dir, str) else "",
                        library_path=steamapps,
                        size_on_disk=int(size_raw) if str(size_raw).isdigit() else 0,
                    )
                )

    games.sort(key=lambda g: g.name.lower())

    # Deduplikacja po app_id - ta sama gra potrafi mieć manifest w więcej niż
    # jednej bibliotece (np. resztka po przeniesieniu na inny dysk, albo
    # niespójny stan po przerwanej migracji) - zostawiamy pierwsze trafienie.
    seen_ids: set[int] = set()
    unique_games: list[InstalledGame] = []
    for game in games:
        if game.app_id not in seen_ids:
            seen_ids.add(game.app_id)
            unique_games.append(game)

    return unique_games


def find_running_steam_pid() -> int | None:
    """Sprawdza, czy klient Steam jest uruchomiony (wymagane zarówno dla
    achievementów jak i idle - Steamworks nie działa bez żywego klienta)."""
    import psutil

    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in ("steam", "steamwebhelper"):
            return proc.pid
    return None
