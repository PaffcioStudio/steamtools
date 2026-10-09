"""
Osiągnięcia w OSOBNYM, krótkotrwałym procesie.

Steam uznaje grę za "Uruchomioną" od SteamAPI_Init() aż do zakończenia
procesu, który ją zainicjował - samo SteamAPI_Shutdown() w żywym procesie
nie zawsze zdejmuje ten status (zwłaszcza dla gry niezainstalowanej, której
nie da się potem "zatrzymać" z poziomu Steama). Dlatego, tak samo jak SAM
(osobny SAM.Game.exe na grę) i idler, każdą operację na osiągnięciach
wykonujemy w procesie potomnym, który po skończonej pracy po prostu kończy
się - Steam widzi wtedy zakończenie gry i zwalnia status.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time

from steamtools.core.logging_setup import get_logger

from steamtools.core.steamworks import AchievementInfo, SteamClient, SteamworksError

_TIMEOUT_S = 45
_log = get_logger("achievements")


def _worker(app_id: int, changes: dict | None, out) -> None:
    try:
        with SteamClient(app_id=app_id) as client:
            if changes is None:
                out.put(("ok", client.get_achievements(), ""))
                return
            for api_name, unlocked in changes.items():
                client.set_achievement(api_name, unlocked)
            stored = client.store_stats()
            # StoreStats jest asynchroniczne - dajemy klientowi Steam chwilę
            # na wysłanie zmian, zanim proces (i sesja) się zakończy.
            for _ in range(15):
                client.run_callbacks()
                time.sleep(0.1)
            out.put(("ok", stored, ""))
    except SteamworksError as exc:
        out.put(("err", str(exc), exc.kind))
    except Exception as exc:  # noqa: BLE001 - błąd ma wrócić do UI, nie zabić wątku
        out.put(("err", f"Nieoczekiwany błąd: {exc}", "generic"))


def _run(app_id: int, changes: dict | None):
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    process = ctx.Process(target=_worker, args=(app_id, changes, out), daemon=True)
    process.start()
    try:
        status, value, kind = out.get(timeout=_TIMEOUT_S)
    except queue.Empty:
        status, value, kind = "err", "Steam nie odpowiedział w limicie czasu.", "timeout"
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
    if status == "err":
        _log.warning("app %s (%s): %s [%s]", app_id, "zapis" if changes is not None else "odczyt", value, kind)
        raise SteamworksError(value, kind)
    return value


def load_achievements(app_id: int) -> list[AchievementInfo]:
    return _run(app_id, None)


def store_achievements(app_id: int, changes: dict[str, bool]) -> bool:
    return _run(app_id, dict(changes))
