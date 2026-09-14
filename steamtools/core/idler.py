"""
Menedżer "farmienia" kart (card idling).

Mechanizm jest identyczny do steam-idle.exe z idle_master_extended:
uruchamiamy osobny, minimalny proces, który robi SteamAPI_Init() dla
danego AppID (przez steam_appid.txt / env SteamAppId) i nic więcej poza
pompowaniem SteamAPI_RunCallbacks() w pętli. Lokalny klient Steam widzi
wtedy ten proces jako "grający w grę X" i po pewnym czasie przydziela
karty kolekcjonerskie tak samo, jakby gra faktycznie działała.

Dlatego, w przeciwieństwie do achievement managera, idler NIE potrzebuje
UI ani okna - to czysto tło. W tym module każdy idlowany AppID to osobny
proces potomny (multiprocessing), żeby:
  - crash/zawieszenie jednej gry nie ubijało reszty kolejki,
  - dało się łatwo pauzować/wznawiać/kończyć pojedynczo (jak przyciski
    play/pause/stop w idle_master_extended -> frmMain.cs).
"""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from steamtools.core.steamworks import SteamClient, SteamworksError
from steamtools.core.config import IdleQueueState, SavedIdleEntry, save_idle_queue, load_idle_queue

# Praktyczny limit oficjalnego klienta Steam na liczbę gier zgłoszonych
# jako "grane" jednocześnie z jednego konta - powyżej tej liczby klient
# Steam sam zaczyna ignorować kolejne zgłoszenia, więc nie ma sensu
# udawać że więcej "działa" - lepiej odmówić z jasnym komunikatem niż
# cicho farmić karty, które i tak się nie naliczą.
MAX_CONCURRENT_IDLE = 32


class IdleQueueFullError(RuntimeError):
    """Rzucane gdy próba dodania kolejnej gry do idle przekroczyłaby
    MAX_CONCURRENT_IDLE."""


class IdleState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()
    ERROR = auto()
    QUEUED = auto()  # czeka na zwolnienie miejsca w limicie MAX_CONCURRENT_IDLE


@dataclass
class IdleJob:
    app_id: int
    name: str
    state: IdleState = IdleState.STOPPED
    process: Optional[mp.Process] = None
    error_message: str = ""
    started_at: Optional[float] = None


def _idle_worker(app_id: int, pause_flag, stop_flag) -> None:
    """Uruchamiane w osobnym procesie. Trzyma SteamClient żywym i pompuje
    callbacki, dopóki stop_flag nie zostanie ustawiony."""
    try:
        client = SteamClient(app_id=app_id)
        client.init()
    except SteamworksError:
        # Sygnalizujemy błąd przez kod wyjścia; proces nadrzędny to wyłapie.
        raise SystemExit(1)

    try:
        while not stop_flag.is_set():
            if not pause_flag.is_set():
                client.run_callbacks()
            time.sleep(1.0)
    finally:
        client.shutdown()


class IdleManager:
    """Trzyma listę aktywnych zadań idle i steruje ich procesami."""

    def __init__(self) -> None:
        self._jobs: dict[int, IdleJob] = {}
        self._ctx = mp.get_context("spawn")

    def jobs(self) -> list[IdleJob]:
        return list(self._jobs.values())

    def start(self, app_id: int, name: str) -> IdleJob:
        existing = self._jobs.get(app_id)
        if existing is not None and existing.state in (
            IdleState.RUNNING, IdleState.PAUSED, IdleState.QUEUED
        ):
            return existing

        # Limit klienta Steam - patrz komentarz przy MAX_CONCURRENT_IDLE.
        # Liczymy zadania RUNNING/PAUSED (zajmują realne miejsce - proces
        # trzyma żywą sesję Steamworks nawet w pauzie) - QUEUED nie liczy
        # się do limitu, bo to zadania BEZ procesu, czekające na miejsce.
        active_count = sum(
            1 for job in self._jobs.values()
            if job.state in (IdleState.RUNNING, IdleState.PAUSED)
        )

        if active_count >= MAX_CONCURRENT_IDLE:
            # Zamiast twardej odmowy - kolejkujemy grę. Gdy zwolni się
            # miejsce (user zatrzyma jedną z aktywnych gier, albo auto-stop
            # po wyczerpaniu kart w IdleView), pierwsza gra z kolejki
            # zostanie automatycznie awansowana i uruchomiona - patrz
            # _promote_from_queue(), wołane na końcu stop().
            job = IdleJob(app_id=app_id, name=name, state=IdleState.QUEUED)
            self._jobs[app_id] = job
            return job

        return self._launch(app_id, name)

    def _launch(self, app_id: int, name: str) -> IdleJob:
        """Faktycznie uruchamia proces idle dla danej gry - wydzielone z
        start(), żeby _promote_from_queue() mogło to wywołać bez
        powtarzania logiki liczenia limitu (w momencie promocji miejsce
        już wiadomo że jest wolne, bo wywołujemy to zaraz po stop())."""
        pause_flag = self._ctx.Event()
        stop_flag = self._ctx.Event()
        process = self._ctx.Process(
            target=_idle_worker,
            args=(app_id, pause_flag, stop_flag),
            daemon=True,
        )
        process.start()

        job = IdleJob(app_id=app_id, name=name, state=IdleState.RUNNING, process=process)
        job.started_at = time.time()
        # Przechowujemy flagi na obiekcie procesu, żeby móc je odzyskać.
        job._pause_flag = pause_flag  # type: ignore[attr-defined]
        job._stop_flag = stop_flag  # type: ignore[attr-defined]
        self._jobs[app_id] = job
        return job

    def _promote_from_queue(self) -> Optional[IdleJob]:
        """Wywoływane po zwolnieniu miejsca (stop()) - jeśli w kolejce
        oczekującej (QUEUED) jest jakaś gra, uruchamia najstarszą z nich
        (kolejność FIFO, tak jak to działa w idle_master_extended przy
        limitowaniu jednocześnie farmionych gier)."""
        queued = [j for j in self._jobs.values() if j.state == IdleState.QUEUED]
        if not queued:
            return None
        next_job = queued[0]
        return self._launch(next_job.app_id, next_job.name)

    def pause(self, app_id: int) -> None:
        job = self._jobs.get(app_id)
        if job and job.process is not None:
            job._pause_flag.set()  # type: ignore[attr-defined]
            job.state = IdleState.PAUSED

    def resume(self, app_id: int) -> None:
        job = self._jobs.get(app_id)
        if job and job.process is not None:
            job._pause_flag.clear()  # type: ignore[attr-defined]
            job.state = IdleState.RUNNING

    def stop(self, app_id: int, *, promote: bool = True) -> None:
        job = self._jobs.get(app_id)
        if job is None:
            return

        if job.state == IdleState.QUEUED:
            # Gra czekająca w kolejce nie ma procesu do zabicia - po prostu
            # usuwamy ją z listy, bez wpływu na limit (nie zajmowała miejsca).
            del self._jobs[app_id]
            return

        if job.process is not None:
            job._stop_flag.set()  # type: ignore[attr-defined]
            job.process.join(timeout=5)
            if job.process.is_alive():
                job.process.terminate()
            job.state = IdleState.STOPPED
            del self._jobs[app_id]

            # Zwolniło się miejsce w limicie - jeśli ktoś czeka w kolejce,
            # awansuj go automatycznie (patrz Etap 3 z ROADMAP: "automatyczne
            # przełączanie gdy jedna się skończy"). Pomijalne przez
            # `promote=False` - używane przez stop_all(), gdzie promowanie
            # gry z kolejki tylko po to, żeby zaraz ją też zatrzymać w
            # kolejnej iteracji tej samej pętli, byłoby czystym marnotrawstwem
            # (niepotrzebne odpalenie i natychmiastowe ubicie procesu).
            if promote:
                self._promote_from_queue()

    def stop_all(self) -> None:
        for app_id in list(self._jobs.keys()):
            self.stop(app_id, promote=False)

    def poll(self) -> None:
        """Wywoływać cyklicznie z QTimer w UI, żeby wykryć procesy które
        padły (np. brak gry na koncie, klient Steam zamknięty)."""
        for app_id, job in list(self._jobs.items()):
            if job.process is not None and not job.process.is_alive():
                exitcode = job.process.exitcode
                if exitcode not in (0, None):
                    job.state = IdleState.ERROR
                    job.error_message = f"Proces zakończył się kodem {exitcode}"
                else:
                    job.state = IdleState.STOPPED

    # ------------------------------------------------------------------ #
    # Persystencja kolejki między uruchomieniami aplikacji (Etap 3 z
    # ROADMAP) - zapisujemy AppID/nazwę/stan pauzy każdej farmionej gry do
    # ~/.config/steamtools/idle_queue.json, żeby po ponownym uruchomieniu
    # aplikacji dało się zaproponować userowi wznowienie dokładnie tej
    # samej kolejki zamiast zaczynać od zera.
    # ------------------------------------------------------------------ #

    def save_queue(self) -> None:
        """Zapisuje aktualny stan kolejki do pliku. Wywoływane po każdej
        zmianie (start/stop/pause/resume) z UI, żeby stan na dysku nigdy
        nie był bardziej niż jedną zmianę "do tyłu" względem pamięci -
        w razie np. twardego zamknięcia aplikacji (SIGKILL, awaria
        systemu) tracimy najwyżej jedną, ostatnią zmianę, nie całą kolejkę.

        Uwzględnia też gry w stanie QUEUED (czekające na zwolnienie
        miejsca) - inaczej kolejka oczekująca zniknęłaby przy restarcie
        aplikacji, mimo że sama lista aktywnych gier by przetrwała. Przy
        wznowieniu (IdleView.prompt_resume_saved_queue) i tak wołamy
        start() dla każdego wpisu, które samo poprawnie zdecyduje czy
        uruchomić od razu, czy z powrotem zakolejkować, bazując na
        aktualnym stanie limitu w danym momencie."""
        entries = [
            SavedIdleEntry(
                app_id=job.app_id,
                name=job.name,
                was_paused=(job.state == IdleState.PAUSED),
            )
            for job in self._jobs.values()
            if job.state in (IdleState.RUNNING, IdleState.PAUSED, IdleState.QUEUED)
        ]
        save_idle_queue(IdleQueueState(entries=entries))

    @staticmethod
    def load_saved_queue() -> list[SavedIdleEntry]:
        """Zwraca zapisaną kolejkę z poprzedniej sesji (bez jej
        uruchamiania) - UI decyduje, czy i jak zapytać użytkownika o
        wznowienie, np. jednym dialogiem przy starcie aplikacji."""
        return load_idle_queue().entries
