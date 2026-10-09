"""
Przyjazne komunikaty o błędach Steamworks zamiast surowego tekstu wyjątku.

Każdy SteamworksError ma `kind` (patrz core/steamworks.py), który mówi, CO
poszło nie tak, więc UI może od razu podpowiedzieć, co zrobić. `kind` jest
też przekazywany przez granicę procesów (kod wyjścia procesu idle, pole w
odpowiedzi procesu osiągnięć), bo tekst wyjątku nie przeżywa spawn.
"""

from __future__ import annotations

from steamtools.core.steamworks import SteamworksError

# kind -> (tytuł, wskazówka co zrobić)
_FRIENDLY: dict[str, tuple[str, str]] = {
    "not_running": (
        "Steam nie jest uruchomiony",
        "Uruchom klienta Steam i zaloguj się na to samo konto, potem spróbuj ponownie.",
    ),
    "not_owned": (
        "Nie można otworzyć tej gry",
        "Steam nie udostępnia statystyk tej gry temu kontem. Sprawdź, czy gra jest "
        "na koncie (nie tylko w Family Sharing) i czy ma osiągnięcia.",
    ),
    "lib_missing": (
        "Brak biblioteki Steamworks",
        "Nie znaleziono libsteam_api.so. Umieść ją w steamtools/vendor/linux64/ "
        "albo zainstaluj aplikację z oficjalnej paczki.",
    ),
    "timeout": (
        "Steam nie odpowiedział",
        "Klient Steam nie odpowiedział w limicie czasu. Sprawdź, czy Steam jest "
        "online (nie w trybie offline) i spróbuj ponownie.",
    ),
    "generic": (
        "Błąd Steamworks",
        "",
    ),
}

# Kody wyjścia procesu idle (0 = ok, 1 = nieokreślony błąd).
_EXIT_CODES = {"generic": 1, "not_running": 10, "not_owned": 11, "lib_missing": 12, "timeout": 13}
_KIND_BY_EXIT_CODE = {code: kind for kind, code in _EXIT_CODES.items()}


def friendly_error(exc: SteamworksError) -> tuple[str, str]:
    """Zwraca (tytuł, treść) do pokazania userowi. Dla nieznanego rodzaju
    błędu treścią jest surowy komunikat, żeby nic nie zginęło."""
    title, hint = _FRIENDLY.get(getattr(exc, "kind", "generic"), _FRIENDLY["generic"])
    raw = str(exc)
    if not hint:
        return title, raw
    return title, hint


def exit_code_for(exc: SteamworksError) -> int:
    return _EXIT_CODES.get(getattr(exc, "kind", "generic"), 1)


def describe_exit_code(code: int) -> str:
    """Krótki opis zakończenia procesu idle po kodzie wyjścia."""
    kind = _KIND_BY_EXIT_CODE.get(code)
    if kind is None or kind == "generic":
        return f"Proces zakończył się kodem {code}"
    title, hint = _FRIENDLY[kind]
    return f"{title}. {hint}"
