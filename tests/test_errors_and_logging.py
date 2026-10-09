import logging

from steamtools.core import errors, logging_setup
from steamtools.core.steamworks import (
    GameNotOwnedError, SteamLibraryMissingError, SteamNotRunningError, SteamworksError,
)


def test_friendly_titles_by_kind():
    assert errors.friendly_error(SteamNotRunningError("x"))[0] == "Steam nie jest uruchomiony"
    assert errors.friendly_error(GameNotOwnedError("x"))[0] == "Nie można otworzyć tej gry"
    assert errors.friendly_error(SteamLibraryMissingError("x"))[0] == "Brak biblioteki Steamworks"
    assert errors.friendly_error(SteamworksError("surowy tekst")) == ("Błąd Steamworks", "surowy tekst")


def test_kind_survives_process_boundary():
    exc = SteamworksError("msg", "timeout")
    assert exc.kind == "timeout" and errors.friendly_error(exc)[0] == "Steam nie odpowiedział"


def test_exit_codes_roundtrip():
    for exc in (SteamNotRunningError("x"), GameNotOwnedError("x"), SteamLibraryMissingError("x")):
        code = errors.exit_code_for(exc)
        assert code != 1
        assert errors.describe_exit_code(code).startswith(errors.friendly_error(exc)[0])
    assert errors.describe_exit_code(1) == "Proces zakończył się kodem 1"


def test_logging_writes_file(monkeypatch):
    logger = logging.getLogger("steamtools")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    if hasattr(logger, "_steamtools_configured"):
        del logger._steamtools_configured
    path = logging_setup.setup_logging("test")
    logging_setup.get_logger("x").warning("zdarzenie testowe")
    for handler in logger.handlers:
        handler.flush()
    assert path is not None and "zdarzenie testowe" in path.read_text(encoding="utf-8")
