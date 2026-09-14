"""
Cienki wrapper ctypes na Steamworks SDK "flat" C API (steam_api_flat.h).

Dlaczego flat API a nie odtwarzanie vtable jak w SAM.API (C#)?
SAM (SteamAchievementManager) robi CreateInterface() i ręcznie wywołuje
metody wirtualne C++ przez offsety w vtable (patrz SAM.API/Wrappers/*.cs,
klasa NativeWrapper). To działa, ale jest kruche i różni się między
wersjami SDK/kompilatorów.

Steamworks SDK od dawna eksportuje też "flat" wersję API - zwykłe funkcje C
(SteamAPI_ISteamUserStats_SetAchievement, itd.) zaprojektowane właśnie do
bindowania z innych języków. To jest dużo bezpieczniejsze pod ctypes/cffi
i to na nim opiera się ten moduł.

Wymaga pliku libsteam_api.so (Linux) z oficjalnego Steamworks SDK - NIE jest
on dołączony do tego repo (licencja Valve). Umieść go w:
    steamtools/vendor/linux64/libsteam_api.so
oraz plik `steam_appid.txt` z AppID w katalogu roboczym procesu przed
wywołaniem init() (wymóg Steamworks przy uruchamianiu poza Steam launcherem).
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class SteamworksError(RuntimeError):
    """Błąd inicjalizacji lub komunikacji ze Steamworks API."""


# Wartości enum ESteamAPIInitResult (steam_api.h) - potrzebne do
# interpretacji wyniku SteamAPI_InitFlat().
K_ESTEAM_API_INIT_RESULT_OK = 0
K_ESTEAM_API_INIT_RESULT_FAILED_GENERIC = 1
K_ESTEAM_API_INIT_RESULT_NO_STEAM_CLIENT = 2
K_ESTEAM_API_INIT_RESULT_VERSION_MISMATCH = 3

_INIT_RESULT_MESSAGES = {
    K_ESTEAM_API_INIT_RESULT_FAILED_GENERIC: "Nieznany błąd inicjalizacji Steamworks.",
    K_ESTEAM_API_INIT_RESULT_NO_STEAM_CLIENT: (
        "Nie można połączyć się z klientem Steam - czy Steam jest uruchomiony "
        "i zalogowany?"
    ),
    K_ESTEAM_API_INIT_RESULT_VERSION_MISMATCH: (
        "Klient Steam wygląda na nieaktualny względem wersji SDK."
    ),
}

# Rozmiar bufora SteamErrMsg z steam_api_common.h (k_cchMaxSteamErrMsg).
_STEAM_ERR_MSG_SIZE = 1024


def _vendor_lib_path() -> Path:
    """Ścieżka do libsteam_api.so w zależności od architektury/platformy."""
    base = Path(__file__).resolve().parent.parent / "vendor"
    if sys.platform.startswith("linux"):
        arch_dir = "linux64" if sys.maxsize > 2**32 else "linux32"
        return base / arch_dir / "libsteam_api.so"
    if sys.platform == "darwin":
        return base / "osx" / "libsteam_api.dylib"
    if sys.platform == "win32":
        return base / ("win64" if sys.maxsize > 2**32 else "win32") / "steam_api64.dll"
    raise SteamworksError(f"Niewspierana platforma: {sys.platform}")


@dataclass
class AchievementInfo:
    api_name: str
    display_name: str
    description: str
    is_achieved: bool
    unlock_time: int
    hidden: bool
    icon_normal: str = ""
    icon_locked: str = ""


@dataclass
class StatInfo:
    api_name: str
    kind: str  # "int" | "float"
    value: float | int


def is_steam_running() -> bool:
    """Szybkie sprawdzenie czy klient Steam jest uruchomiony, bez pełnej
    inicjalizacji sesji dla konkretnego AppID. Używane w UI np. do pokazania
    statusu na pasku/w ustawieniach zanim user wybierze grę.

    Woła SteamAPI_IsSteamRunning() z libsteam_api.so - jeśli biblioteka nie
    jest jeszcze dostępna (brak pliku), zwraca False zamiast rzucać wyjątek,
    żeby UI mogło się z tym gładko obsłużyć.
    """
    lib_path = _vendor_lib_path()
    if not lib_path.exists():
        return False
    try:
        lib = ctypes.CDLL(str(lib_path))
        lib.SteamAPI_IsSteamRunning.argtypes = []
        lib.SteamAPI_IsSteamRunning.restype = ctypes.c_bool
        return bool(lib.SteamAPI_IsSteamRunning())
    except OSError:
        return False


class SteamClient:
    """
    Jedna sesja Steamworks dla JEDNEGO AppID (analogicznie do SAM.Game -
    tam też każdy proces "udaje" się za jedną grę na raz, bo Steam client
    rozróżnia kontekst po pliku steam_appid.txt / zmiennej środowiskowej
    SteamAppId ustawionej przed SteamAPI_Init()).

    Użycie:
        with SteamClient(app_id=440) as client:
            for ach in client.get_achievements():
                print(ach.api_name, ach.is_achieved)
            client.set_achievement("ACH_WIN_ONE_GAME", True)
            client.store_stats()
    """

    def __init__(self, app_id: int, lib_path: Optional[Path] = None):
        self.app_id = app_id
        self._lib_path = lib_path or _vendor_lib_path()
        self._lib: Optional[ctypes.CDLL] = None
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Cykl życia
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "SteamClient":
        self.init()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()

    def init(self) -> None:
        if self._initialized:
            return

        if not self._lib_path.exists():
            raise SteamworksError(
                f"Brak {self._lib_path}. Umieść libsteam_api.so z oficjalnego "
                f"Steamworks SDK w steamtools/vendor/linux64/."
            )

        # Steam wymaga pliku steam_appid.txt w cwd LUB zmiennej env
        # SteamAppId, gdy proces nie jest odpalony przez sam klient Steam.
        os.environ["SteamAppId"] = str(self.app_id)
        os.environ["SteamGameId"] = str(self.app_id)

        self._lib = ctypes.CDLL(str(self._lib_path))
        self._bind_signatures()

        if not self._lib.SteamAPI_IsSteamRunning():
            raise SteamworksError(
                "Klient Steam nie jest uruchomiony. Uruchom Steam, zaloguj się "
                "i spróbuj ponownie."
            )

        err_msg = ctypes.create_string_buffer(_STEAM_ERR_MSG_SIZE)
        result = self._lib.SteamAPI_InitFlat(err_msg)

        if result != K_ESTEAM_API_INIT_RESULT_OK:
            detail = err_msg.value.decode("utf-8", errors="ignore").strip()
            reason = _INIT_RESULT_MESSAGES.get(result, f"Kod błędu {result}.")
            message = reason if not detail else f"{reason} ({detail})"
            raise SteamworksError(f"SteamAPI_InitFlat nie powiodło się: {message}")

        self._initialized = True

        # Trzeba poprosić o statystyki zanim cokolwiek odczytasz/zapiszesz -
        # patrz SAM.Game/Manager.cs -> RequestCurrentStats().
        user_stats = self._lib.SteamAPI_SteamUserStats_v013()
        if not user_stats:
            self._initialized = False
            raise SteamworksError(
                "Nie udało się pobrać interfejsu ISteamUserStats - czy "
                "posiadasz tę grę (AppID {}) na koncie Steam?".format(self.app_id)
            )
        self._user_stats = user_stats
        # RequestCurrentStats() nie jest już częścią API - wg komentarza w
        # isteamuserstats.h: "this call is no longer required as it is
        # managed by the Steam client. The game stats and achievements will
        # be synchronized with Steam before the game process begins."

    def shutdown(self) -> None:
        if self._initialized and self._lib is not None:
            self._lib.SteamAPI_Shutdown()
        self._initialized = False

    def run_callbacks(self) -> None:
        """Steam wymaga cyklicznego pompowania callbacków (podobnie jak
        SteamAPI_RunCallbacks w pętli SAM.Game)."""
        if self._lib is not None:
            self._lib.SteamAPI_RunCallbacks()

    # ------------------------------------------------------------------ #
    # Sygnatury C - tylko te faktycznie używane (odpowiednik zestawu
    # wywołań z SAM.Game/Manager.cs: GetAchievements/SetAchievement/
    # GetStatistics/SetStatValue/StoreStats)
    # ------------------------------------------------------------------ #

    def _bind_signatures(self) -> None:
        lib = self._lib
        assert lib is not None

        # WAŻNE: w nowszych wersjach Steamworks SDK (flat API, v1.60+)
        # `SteamAPI_Init()` jest funkcją INLINE zdefiniowaną w steam_api.h,
        # nie jest eksportowana z libsteam_api.so - woła w środku
        # `SteamInternal_SteamAPI_Init` z zaszytą na sztywno listą wersji
        # wszystkich interfejsów (STEAMUSERSTATS_INTERFACE_VERSION itd.),
        # które musiałyby się zgadzać z konkretnym headerem SDK użytym do
        # kompilacji - kruche do odtwarzania w Pythonie.
        #
        # Zamiast tego używamy `SteamAPI_InitFlat`, które JEST eksportowane
        # i nie wymaga podawania wersji interfejsów z góry - dokładnie po to
        # zostało dodane do flat API (patrz steam_api.h: "Same usage as
        # SteamAPI_InitEx(), however does not verify ISteam* interfaces").
        lib.SteamAPI_InitFlat.argtypes = [ctypes.c_char_p]
        lib.SteamAPI_InitFlat.restype = ctypes.c_int32  # ESteamAPIInitResult

        lib.SteamAPI_IsSteamRunning.argtypes = []
        lib.SteamAPI_IsSteamRunning.restype = ctypes.c_bool

        lib.SteamAPI_Shutdown.restype = None
        lib.SteamAPI_RunCallbacks.restype = None

        lib.SteamAPI_SteamUserStats_v013.restype = ctypes.c_void_p

        lib.SteamAPI_ISteamUserStats_GetNumAchievements.argtypes = [ctypes.c_void_p]
        lib.SteamAPI_ISteamUserStats_GetNumAchievements.restype = ctypes.c_uint32

        lib.SteamAPI_ISteamUserStats_GetAchievementName.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32,
        ]
        lib.SteamAPI_ISteamUserStats_GetAchievementName.restype = ctypes.c_char_p

        lib.SteamAPI_ISteamUserStats_GetAchievementAndUnlockTime.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_bool),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.SteamAPI_ISteamUserStats_GetAchievementAndUnlockTime.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_GetAchievementDisplayAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        lib.SteamAPI_ISteamUserStats_GetAchievementDisplayAttribute.restype = ctypes.c_char_p

        lib.SteamAPI_ISteamUserStats_SetAchievement.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p,
        ]
        lib.SteamAPI_ISteamUserStats_SetAchievement.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_ClearAchievement.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p,
        ]
        lib.SteamAPI_ISteamUserStats_ClearAchievement.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_GetStatInt32.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32),
        ]
        lib.SteamAPI_ISteamUserStats_GetStatInt32.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_GetStatFloat.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_float),
        ]
        lib.SteamAPI_ISteamUserStats_GetStatFloat.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_SetStatInt32.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
        ]
        lib.SteamAPI_ISteamUserStats_SetStatInt32.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_SetStatFloat.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_float,
        ]
        lib.SteamAPI_ISteamUserStats_SetStatFloat.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_StoreStats.argtypes = [ctypes.c_void_p]
        lib.SteamAPI_ISteamUserStats_StoreStats.restype = ctypes.c_bool

        lib.SteamAPI_ISteamUserStats_ResetAllStats.argtypes = [
            ctypes.c_void_p, ctypes.c_bool,
        ]
        lib.SteamAPI_ISteamUserStats_ResetAllStats.restype = ctypes.c_bool

    # ------------------------------------------------------------------ #
    # Achievements - odpowiednik Manager.GetAchievements() / SetAchievement()
    # ------------------------------------------------------------------ #

    def get_achievements(self) -> list[AchievementInfo]:
        self._require_init()
        lib = self._lib
        count = lib.SteamAPI_ISteamUserStats_GetNumAchievements(self._user_stats)

        results: list[AchievementInfo] = []
        for i in range(count):
            raw_name = lib.SteamAPI_ISteamUserStats_GetAchievementName(
                self._user_stats, i
            )
            if not raw_name:
                continue
            name = raw_name.decode("utf-8")

            is_achieved = ctypes.c_bool(False)
            unlock_time = ctypes.c_uint32(0)
            lib.SteamAPI_ISteamUserStats_GetAchievementAndUnlockTime(
                self._user_stats,
                name.encode("utf-8"),
                ctypes.byref(is_achieved),
                ctypes.byref(unlock_time),
            )

            display_name = self._get_attr(name, "name") or name
            description = self._get_attr(name, "desc") or ""
            hidden = self._get_attr(name, "hidden") == "1"

            results.append(
                AchievementInfo(
                    api_name=name,
                    display_name=display_name,
                    description=description,
                    is_achieved=bool(is_achieved.value),
                    unlock_time=int(unlock_time.value),
                    hidden=hidden,
                )
            )
        return results

    def _get_attr(self, api_name: str, key: str) -> str:
        raw = self._lib.SteamAPI_ISteamUserStats_GetAchievementDisplayAttribute(
            self._user_stats, api_name.encode("utf-8"), key.encode("utf-8")
        )
        return raw.decode("utf-8") if raw else ""

    def set_achievement(self, api_name: str, unlocked: bool = True) -> bool:
        """Odpowiednik Manager.cs -> SteamUserStats.SetAchievement(...)."""
        self._require_init()
        if unlocked:
            return bool(
                self._lib.SteamAPI_ISteamUserStats_SetAchievement(
                    self._user_stats, api_name.encode("utf-8")
                )
            )
        return bool(
            self._lib.SteamAPI_ISteamUserStats_ClearAchievement(
                self._user_stats, api_name.encode("utf-8")
            )
        )

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #

    def get_stat_int(self, api_name: str) -> Optional[int]:
        self._require_init()
        value = ctypes.c_int32(0)
        ok = self._lib.SteamAPI_ISteamUserStats_GetStatInt32(
            self._user_stats, api_name.encode("utf-8"), ctypes.byref(value)
        )
        return int(value.value) if ok else None

    def get_stat_float(self, api_name: str) -> Optional[float]:
        self._require_init()
        value = ctypes.c_float(0.0)
        ok = self._lib.SteamAPI_ISteamUserStats_GetStatFloat(
            self._user_stats, api_name.encode("utf-8"), ctypes.byref(value)
        )
        return float(value.value) if ok else None

    def set_stat_int(self, api_name: str, value: int) -> bool:
        self._require_init()
        return bool(
            self._lib.SteamAPI_ISteamUserStats_SetStatInt32(
                self._user_stats, api_name.encode("utf-8"), int(value)
            )
        )

    def set_stat_float(self, api_name: str, value: float) -> bool:
        self._require_init()
        return bool(
            self._lib.SteamAPI_ISteamUserStats_SetStatFloat(
                self._user_stats, api_name.encode("utf-8"), float(value)
            )
        )

    def store_stats(self) -> bool:
        """Musi być wywołane po SetAchievement/SetStat, inaczej zmiany nie
        zostaną wysłane do Steam (dokładnie jak w SAM: przycisk "Store")."""
        self._require_init()
        return bool(self._lib.SteamAPI_ISteamUserStats_StoreStats(self._user_stats))

    def reset_all_stats(self, also_achievements: bool = False) -> bool:
        self._require_init()
        return bool(
            self._lib.SteamAPI_ISteamUserStats_ResetAllStats(
                self._user_stats, also_achievements
            )
        )

    def _require_init(self) -> None:
        if not self._initialized:
            raise SteamworksError("SteamClient nie jest zainicjalizowany (wywołaj init()).")
