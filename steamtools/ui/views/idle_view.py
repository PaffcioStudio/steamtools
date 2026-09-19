"""Widok "Farma kart" - kolejka gier idlowanych równolegle, z kontrolkami
play/pause/stop per gra. Odpowiednik frmMain.cs z idle_master_extended
(lista "gry do zidlowania" + przyciski media-play/media-pause)."""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel,
    CaptionLabel,
    BodyLabel,
    StrongBodyLabel,
    CardWidget,
    TransparentToolButton,
    PushButton,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    MessageBox,
    IndeterminateProgressBar,
)

from steamtools.core.idler import IdleManager, IdleState, IdleJob, MAX_CONCURRENT_IDLE
from steamtools.core.badges import (
    fetch_badge_progress,
    SteamCommunityError,
    BadgeProgress,
    format_cards_count,
    get_cached_badge_progress,
    set_cached_badge_progress,
)
from steamtools.core.config import load_community_session


_STATE_LABELS = {
    IdleState.RUNNING: ("Aktywne", "#2ecc71"),
    IdleState.PAUSED: ("Wstrzymane", "#f39c12"),
    IdleState.STOPPED: ("Zatrzymane", "#95a5a6"),
    IdleState.ERROR: ("Błąd", "#e74c3c"),
    IdleState.QUEUED: ("W kolejce", "#3498db"),
}


class _FetchBadgeProgressThread(QThread):
    """Zapytanie HTTP do Steam Community w osobnym wątku - bez tego UI
    zamrażałoby się na czas requestu (do kilku sekund przy wolnym łączu)."""

    finished_ok = pyqtSignal(list)  # list[BadgeProgress]
    finished_error = pyqtSignal(str)

    def __init__(self, session_cookie: str, session_id: str, parent=None):
        super().__init__(parent)
        self.session_cookie = session_cookie
        self.session_id = session_id

    def run(self) -> None:
        try:
            results = fetch_badge_progress(self.session_cookie, self.session_id)
            self.finished_ok.emit(results)
        except SteamCommunityError as exc:
            self.finished_error.emit(str(exc))


class IdleJobCard(CardWidget):
    stopRequested = pyqtSignal(int)
    pauseRequested = pyqtSignal(int)
    resumeRequested = pyqtSignal(int)

    def __init__(self, job: IdleJob, parent=None):
        super().__init__(parent)
        self.app_id = job.app_id
        self.cards_remaining: Optional[int] = None
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        text_col = QVBoxLayout()
        self.title = StrongBodyLabel(job.name, self)
        self.subtitle = CaptionLabel("", self)
        text_col.addWidget(self.title)
        text_col.addWidget(self.subtitle)
        layout.addLayout(text_col, stretch=1)

        self.cards_pill = PillPushButton("", self)
        self.cards_pill.setCheckable(False)
        self.cards_pill.setVisible(False)
        layout.addWidget(self.cards_pill)

        self.status_pill = PillPushButton("", self)
        self.status_pill.setCheckable(False)
        layout.addWidget(self.status_pill)

        self.pause_btn = TransparentToolButton(FluentIcon.PAUSE, self)
        self.stop_btn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.stop_btn.clicked.connect(lambda: self.stopRequested.emit(self.app_id))
        layout.addWidget(self.pause_btn)
        layout.addWidget(self.stop_btn)

        self.update_state(job)

    def _on_pause_clicked(self) -> None:
        if self.pause_btn.property("paused"):
            self.resumeRequested.emit(self.app_id)
        else:
            self.pauseRequested.emit(self.app_id)

    def set_cards_remaining(self, count: Optional[int]) -> None:
        """Ustawia widoczną liczbę pozostałych kart. `None` oznacza "nie
        sprawdzano jeszcze" - wtedy pill jest ukryty zamiast pokazywać
        mylącą wartość."""
        self.cards_remaining = count
        if count is None:
            self.cards_pill.setVisible(False)
            return
        self.cards_pill.setVisible(True)
        self.cards_pill.setText(format_cards_count(count))

    def update_state(self, job: IdleJob) -> None:
        label, _color = _STATE_LABELS.get(job.state, ("?", "#95a5a6"))
        self.status_pill.setText(label)

        is_paused = job.state == IdleState.PAUSED
        self.pause_btn.setProperty("paused", is_paused)
        self.pause_btn.setIcon(FluentIcon.PLAY if is_paused else FluentIcon.PAUSE)
        # Gra QUEUED nie ma jeszcze procesu - pauza/wznowienie nie ma tu
        # zastosowania, dopóki nie zostanie automatycznie awansowana.
        self.pause_btn.setEnabled(job.state != IdleState.QUEUED)

        if job.state == IdleState.QUEUED:
            self.subtitle.setText(f"AppID {job.app_id} - czeka na zwolnienie miejsca")
        elif job.started_at:
            elapsed_min = int((time.time() - job.started_at) // 60)
            self.subtitle.setText(f"AppID {job.app_id} - {elapsed_min} min")
        else:
            self.subtitle.setText(f"AppID {job.app_id}")

        if job.state == IdleState.ERROR:
            self.subtitle.setText(f"{self.subtitle.text()} - {job.error_message}")


class IdleView(QWidget):
    # Co ile sekund automatycznie sprawdzamy pozostałe karty w tle, bez
    # klikania. 5 minut to rozsądny kompromis: wystarczająco często żeby
    # nie farmić "na pusto" długo po wyczerpaniu kart danej gry, a
    # jednocześnie rzadko na tyle, żeby nie ryzykować throttlingu/podejrzeń
    # o boty ze strony Steam Community przy regularnych zapytaniach do
    # prywatnej strony Badges.
    AUTO_CHECK_INTERVAL_SECONDS = 300

    # Emitowany za KAŻDYM razem, gdy pojedyncza gra zostaje automatycznie
    # zatrzymana z powodu wyczerpania kart (0 pozostałych) - niezależnie
    # od tego, czy w tym samym momencie kończy się cała kolejka. MainWindow
    # nasłuchuje tego sygnału, żeby pokazać powiadomienie na pulpicie
    # (patrz ustawienie "Powiadomienie o wyczerpaniu kart w grze").
    # Argument: nazwa gry.
    gameCardsExhausted = pyqtSignal(str)

    # Emitowany wyłącznie w momencie, gdy PO zatrzymaniu gry (z powodu
    # wyczerpania kart) kolejka farmienia staje się całkowicie pusta - czyli
    # to była ostatnia aktywnie/pauzowanie farmiona gra. Odróżnione od
    # gameCardsExhausted, bo to dwa osobne ustawienia/powiadomienia: "ta
    # gra skończyła karty" vs "całe farmienie się zakończyło".
    allGamesFinished = pyqtSignal()

    # Emitowany gdy user RĘCZNIE próbuje sprawdzić/dodać gry po kartach
    # (przyciski "Sprawdź pozostałe karty" / "Sprawdź i dodaj wszystkie"),
    # a konto Steam Community nie jest skonfigurowane albo zapisana sesja
    # jest nieważna. MainWindow łapie to i pokazuje dialog z wyborem
    # "Zarządzaj kontem" / "Zamknij" zamiast (albo obok) zwykłego InfoBara -
    # to dokładnie ten sam problem co przy próbie farmienia z nieaktualnym
    # steamLoginSecure, więc user od razu dostaje drogę do naprawy zamiast
    # samego komunikatu o błędzie. NIE emitowany w trybie automatycznym
    # (odpytywanie co 5 minut) - zasypywałoby usera tym samym dialogiem co
    # AUTO_CHECK_INTERVAL_SECONDS, dokładnie to, czemu is_automatic już
    # zapobiega dla zwykłych InfoBarów niżej.
    accountProblemDetected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("IdleView")
        self.manager = IdleManager()
        self._cards: dict[int, IdleJobCard] = {}
        self._badge_thread: Optional[_FetchBadgeProgressThread] = None
        self._auto_check_seconds_left: int = self.AUTO_CHECK_INTERVAL_SECONDS

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.addWidget(TitleLabel("Farma kart", self), stretch=1)
        self.check_cards_btn = PushButton(
            "Sprawdź pozostałe karty", self, FluentIcon.SYNC
        )
        self.check_cards_btn.setToolTip(
            "Sprawdza karty TYLKO dla gier już dodanych do kolejki poniżej "
            "i zatrzymuje te, którym karty się skończyły."
        )
        self.check_cards_btn.clicked.connect(self._check_cards_remaining)
        header_row.addWidget(self.check_cards_btn)

        self.check_and_queue_btn = PushButton(
            "Sprawdź i farm wszystkie", self, FluentIcon.PLAY
        )
        self.check_and_queue_btn.setToolTip(
            "Sprawdza CAŁE konto Steam Community i automatycznie dodaje do "
            "kolejki poniżej każdą grę, która ma jeszcze karty do zdobycia."
        )
        self.check_and_queue_btn.clicked.connect(self._check_and_queue_all_with_cards)
        header_row.addWidget(self.check_and_queue_btn)

        self.count_label = CaptionLabel(f"0 / {MAX_CONCURRENT_IDLE}", self)
        header_row.addWidget(self.count_label)
        root.addLayout(header_row)

        # Licznik odliczający czas do następnego AUTOMATYCZNEGO sprawdzenia
        # kart (osobny mechanizm od ręcznych przycisków powyżej) - żeby
        # było widać, że coś się w ogóle dzieje w tle, zamiast cichej,
        # niewidocznej dla usera automatyki.
        self.auto_check_label = CaptionLabel("", self)
        root.addWidget(self.auto_check_label)

        info = CaptionLabel(
            "Gry poniżej są zgłaszane do klienta Steam jako aktywnie uruchomione, "
            "aby naliczały się karty kolekcjonerskie. Wymaga uruchomionego i "
            "zalogowanego klienta Steam. Liczbę pozostałych kart można sprawdzić "
            "po skonfigurowaniu sesji Steam Community w Ustawieniach.",
            self,
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.badge_progress_bar = IndeterminateProgressBar(self)
        self.badge_progress_bar.setVisible(False)
        root.addWidget(self.badge_progress_bar)

        self.list_widget = QWidget(self)
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        root.addWidget(self.list_widget, stretch=1)

        self.empty_label = BodyLabel(
            "Brak gier w kolejce. Dodaj grę z zakładki Biblioteka.", self
        )
        root.addWidget(self.empty_label)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        # Osobny timer na 1 sekundę, wyłącznie do odliczania wizualnego i
        # wyzwalania automatycznego sprawdzenia kart - celowo NIE ten sam
        # timer co _poll (który jest o stanie procesów Steam, zupełnie
        # inna sprawa), żeby zmiana jednego nie wpływała przypadkiem na
        # częstotliwość drugiego.
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setInterval(1000)
        self._auto_check_timer.timeout.connect(self._on_auto_check_tick)
        self._auto_check_timer.start()

        self._update_empty_state()
        self._update_count_label()
        self._update_auto_check_label()

    def add_game(self, app_id: int, name: str, *, silent: bool = False) -> bool:
        """Dodaje grę do kolejki idle - zawsze się udaje: jeśli osiągnięto
        limit MAX_CONCURRENT_IDLE, gra trafia do kolejki oczekującej
        (stan QUEUED) i zostanie uruchomiona automatycznie, gdy zwolni się
        miejsce (patrz IdleManager._promote_from_queue()). Zwracana wartość
        (zawsze True) zachowana dla kompatybilności wstecznej z
        wywołaniami, które jeszcze sprawdzają wynik.
        Parametr `silent` pomija komunikaty informacyjne - używane przy
        wznawianiu zapisanej kolejki na starcie, gdzie nie ma sensu zalewać
        użytkownika powiadomieniami o czymś co sam zaakceptował."""
        if app_id in self._cards:
            if not silent:
                InfoBar.info(
                    title="Już w kolejce",
                    content=f"{name} jest już farmiona.",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2500,
                )
            return True

        job = self.manager.start(app_id, name)

        card = IdleJobCard(job, self.list_widget)
        card.stopRequested.connect(self._on_stop)
        card.pauseRequested.connect(self._on_pause)
        card.resumeRequested.connect(self._on_resume)
        self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        self._cards[app_id] = card
        self._update_empty_state()
        self._update_count_label()
        self.manager.save_queue()

        # Jeśli karty dla tej gry były już sprawdzone gdzieś indziej (np. w
        # Bibliotece) w tej samej sesji aplikacji, pokazujemy tę wartość od
        # razu - zamiast pustego pilla, dopóki user sam nie kliknie "Sprawdź
        # pozostałe karty" jeszcze raz specjalnie w tej zakładce.
        cached = get_cached_badge_progress()
        if cached is not None:
            by_app_id = {r.app_id: r.cards_remaining for r in cached}
            card.set_cards_remaining(by_app_id.get(app_id, 0))

        if job.state == IdleState.QUEUED and not silent:
            InfoBar.info(
                title="Dodano do kolejki oczekującej",
                content=f"Osiągnięto limit {MAX_CONCURRENT_IDLE} jednocześnie "
                f"farmionych gier. {name} zostanie uruchomiona automatycznie, "
                f"gdy zwolni się miejsce.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        return True

    def _on_stop(self, app_id: int, *, cards_exhausted: bool = False) -> None:
        """Zatrzymuje farmienie danej gry. `cards_exhausted=True` oznacza,
        że to auto-stop z powodu wyczerpania kart (wołane z
        _on_badge_progress_ok) - wtedy, i tylko wtedy, emitujemy sygnały
        powiadomień: zawsze gameCardsExhausted, a dodatkowo allGamesFinished
        jeśli to była ostatnia gra w kolejce. Ręczne zatrzymanie przez usera
        (przycisk X na karcie) nie generuje żadnych powiadomień - to jego
        świadoma akcja, nie ma czego mu "zgłaszać"."""
        name = None
        if cards_exhausted:
            card_before = self._cards.get(app_id)
            if card_before:
                name = card_before.title.text()

        self.manager.stop(app_id)
        card = self._cards.pop(app_id, None)
        if card:
            card.setParent(None)

        # stop() mogło wywołać automatyczną promocję gry z kolejki
        # oczekującej (_promote_from_queue) - jej karta w UI wciąż
        # pokazywałaby stary stan QUEUED, dopóki jej nie odświeżymy.
        for job in self.manager.jobs():
            promoted_card = self._cards.get(job.app_id)
            if promoted_card:
                promoted_card.update_state(job)

        self._update_empty_state()
        self._update_count_label()
        self.manager.save_queue()

        if cards_exhausted and name:
            self.gameCardsExhausted.emit(name)
            # Kolejka pusta PO zatrzymaniu tej gry - to była ostatnia,
            # więc całe farmienie się właśnie zakończyło.
            if not self._cards:
                self.allGamesFinished.emit()

    def _on_pause(self, app_id: int) -> None:
        self.manager.pause(app_id)
        self.manager.save_queue()

    def _on_resume(self, app_id: int) -> None:
        self.manager.resume(app_id)
        self.manager.save_queue()

    def _poll(self) -> None:
        self.manager.poll()
        for job in self.manager.jobs():
            card = self._cards.get(job.app_id)
            if card:
                card.update_state(job)

    def _on_auto_check_tick(self) -> None:
        """Wołane co sekundę - odlicza czas do następnego automatycznego
        sprawdzenia kart i wyzwala je, gdy licznik dojdzie do zera.
        Automatyczne sprawdzenie dotyczy TYLKO gier już w kolejce (ten sam
        zakres co ręczny przycisk "Sprawdź pozostałe karty"), nie dodaje
        nowych gier do farmienia - to celowe: automatyka ma pilnować już
        farmionych gier, a nie samodzielnie rozszerzać kolejkę bez wiedzy
        usera."""
        if not self._cards:
            # Pusta kolejka - nie ma czego sprawdzać, więc nie zużywamy
            # requestu na nic. Odliczanie i tak leci dalej w tle, żeby po
            # dodaniu pierwszej gry nie odpalić sprawdzenia natychmiast.
            self._auto_check_seconds_left -= 1
            if self._auto_check_seconds_left <= 0:
                self._auto_check_seconds_left = self.AUTO_CHECK_INTERVAL_SECONDS
            self._update_auto_check_label()
            return

        self._auto_check_seconds_left -= 1
        if self._auto_check_seconds_left <= 0:
            self._auto_check_seconds_left = self.AUTO_CHECK_INTERVAL_SECONDS
            # Nie odpalamy automatycznego sprawdzenia, jeśli akurat trwa
            # już jakieś inne (ręczne albo poprzednie automatyczne) -
            # _check_cards_remaining i tak sam to sprawdza i wyjdzie
            # bez efektu, ale unikamy tu niepotrzebnego resetu licznika
            # w trakcie trwającego zapytania.
            if self._badge_thread is None or not self._badge_thread.isRunning():
                self._check_cards_remaining(is_automatic=True)
        self._update_auto_check_label()

    def _update_auto_check_label(self) -> None:
        minutes, seconds = divmod(max(self._auto_check_seconds_left, 0), 60)
        if self._cards:
            self.auto_check_label.setText(
                f"Następne automatyczne sprawdzenie kart za {minutes:02d}:{seconds:02d}"
            )
        else:
            self.auto_check_label.setText(
                "Automatyczne sprawdzanie kart włączy się po dodaniu gry do kolejki"
            )

    def _update_empty_state(self) -> None:
        self.empty_label.setVisible(not self._cards)

    def _update_count_label(self) -> None:
        active_count = sum(
            1 for job in self.manager.jobs()
            if job.state in (IdleState.RUNNING, IdleState.PAUSED)
        )
        queued_count = sum(1 for job in self.manager.jobs() if job.state == IdleState.QUEUED)
        text = f"{active_count} / {MAX_CONCURRENT_IDLE}"
        if queued_count:
            text += f"  (+{queued_count} w kolejce)"
        self.count_label.setText(text)

    # ------------------------------------------------------------------ #
    # Sprawdzanie liczby pozostałych kart (Etap 3 z ROADMAP) i auto-stop
    # gier, którym karty się skończyły.
    # ------------------------------------------------------------------ #

    def _check_cards_remaining(self, is_automatic: bool = False) -> None:
        session = load_community_session()
        if not session.is_configured():
            # W trybie automatycznym pomijamy dialog/InfoBar ostrzegawczy -
            # bez tego zamęczałby usera co 5 minut, jeśli świadomie nie
            # skonfigurował sesji Steam Community. Ręczne kliknięcie
            # przycisku to co innego: tam ostrzeżenie jest na miejscu, bo
            # user aktywnie próbuje coś zrobić i zasługuje na wyjaśnienie
            # dlaczego nic się nie stało - stąd też dialog z bezpośrednim
            # skrótem do zakładki Konto, nie tylko gołe info.
            if not is_automatic:
                self.accountProblemDetected.emit(
                    "Żeby sprawdzić liczbę pozostałych kart, najpierw skonfiguruj "
                    "ciasteczko sesji Steam Community w zakładce Konto."
                )
            return

        if self._badge_thread is not None and self._badge_thread.isRunning():
            return  # zapytanie już w toku - nie dubluj

        self.check_cards_btn.setEnabled(False)
        self.check_and_queue_btn.setEnabled(False)
        self.badge_progress_bar.setVisible(True)

        self._badge_thread = _FetchBadgeProgressThread(
            session.session_cookie, session.session_id, self
        )
        self._badge_thread.finished_ok.connect(
            lambda results: self._on_badge_progress_ok(results, is_automatic=is_automatic)
        )
        self._badge_thread.finished_error.connect(
            lambda message: self._on_badge_progress_error(message, is_automatic=is_automatic)
        )
        self._badge_thread.start()
        # Zawsze resetujemy licznik przy każdym sprawdzeniu (ręcznym albo
        # automatycznym) - odliczanie ma zawsze mierzyć czas OD OSTATNIEGO
        # sprawdzenia, nie tylko od startu aplikacji.
        self._auto_check_seconds_left = self.AUTO_CHECK_INTERVAL_SECONDS
        self._update_auto_check_label()

    def _check_and_queue_all_with_cards(self) -> None:
        """Sprawdza CAŁE konto Steam Community i dodaje do kolejki farmienia
        KAŻDĄ grę zwróconą przez scraper (czyli każdą z cards_remaining > 0
        - patrz core/badges.py, strona Badges nie pokazuje gier bez
        dropów). To realizuje żądaną mechanikę "jeden przycisk robi
        wszystko", analogiczną do automatycznego zachowania Idle Master
        Extended widocznego na screenie użytkownika - w przeciwieństwie do
        _check_cards_remaining (który tylko aktualizuje/auto-stopuje gry
        JUŻ w kolejce), ta metoda samodzielnie ROZBUDOWUJE kolejkę o nowe
        gry, więc oba przyciski mają wyraźnie różne, nienachodzące na
        siebie zastosowania."""
        session = load_community_session()
        if not session.is_configured():
            self.accountProblemDetected.emit(
                "Żeby sprawdzić liczbę pozostałych kart, najpierw skonfiguruj "
                "ciasteczko sesji Steam Community w zakładce Konto."
            )
            return

        if self._badge_thread is not None and self._badge_thread.isRunning():
            return  # zapytanie już w toku - nie dubluj

        self.check_cards_btn.setEnabled(False)
        self.check_and_queue_btn.setEnabled(False)
        self.badge_progress_bar.setVisible(True)

        self._badge_thread = _FetchBadgeProgressThread(
            session.session_cookie, session.session_id, self
        )
        self._badge_thread.finished_ok.connect(self._on_badge_progress_queue_all)
        self._badge_thread.finished_error.connect(self._on_badge_progress_error)
        self._badge_thread.start()
        # Ręczne sprawdzenie liczy się jak automatyczne - resetujemy
        # odliczanie, żeby za chwilę nie strzelić drugim requestem tuż po
        # tym co user właśnie zrobił ręcznie.
        self._auto_check_seconds_left = self.AUTO_CHECK_INTERVAL_SECONDS
        self._update_auto_check_label()

    def _on_badge_progress_queue_all(self, results: list[BadgeProgress]) -> None:
        self.check_cards_btn.setEnabled(True)
        self.check_and_queue_btn.setEnabled(True)
        self.badge_progress_bar.setVisible(False)

        set_cached_badge_progress(results)

        added_names: list[str] = []
        for r in results:
            if r.cards_remaining <= 0:
                continue  # dla pewności, chociaż scraper i tak nie zwraca takich
            already_present = r.app_id in self._cards
            self.add_game(r.app_id, r.name, silent=True)
            card = self._cards.get(r.app_id)
            if card:
                card.set_cards_remaining(r.cards_remaining)
            if not already_present:
                added_names.append(r.name)

        self.manager.save_queue()

        if added_names:
            names_preview = ", ".join(added_names[:5])
            if len(added_names) > 5:
                names_preview += f" i {len(added_names) - 5} więcej"
            InfoBar.success(
                title="Dodano do farmienia",
                content=f"Dodano {len(added_names)} gier z kartami do "
                f"zdobycia: {names_preview}.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        else:
            InfoBar.info(
                title="Brak nowych gier",
                content="Wszystkie gry z kartami do zdobycia są już w kolejce farmienia.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )

    def _on_badge_progress_ok(self, results: list[BadgeProgress], is_automatic: bool = False) -> None:
        self.check_cards_btn.setEnabled(True)
        self.check_and_queue_btn.setEnabled(True)
        self.badge_progress_bar.setVisible(False)

        set_cached_badge_progress(results)

        by_app_id = {r.app_id: r.cards_remaining for r in results}

        auto_stopped: list[str] = []
        for app_id, card in list(self._cards.items()):
            # Gra farmiona, ale nieobecna w wynikach scrapowania oznacza 0
            # pozostałych kart - strona Badges pokazuje tylko gry z
            # niewyzerowanymi dropami (patrz docstring w core/badges.py),
            # więc brak wpisu jest równoznaczny z "brak kart do zdobycia".
            remaining = by_app_id.get(app_id, 0)
            card.set_cards_remaining(remaining)

            if remaining == 0:
                name = card.title.text()
                self._on_stop(app_id, cards_exhausted=True)
                auto_stopped.append(name)

        # Zatrzymanie gry (auto_stopped) to zawsze istotna informacja, więc
        # pokazujemy ją niezależnie od tego czy sprawdzenie było ręczne czy
        # automatyczne - to jest cały sens tej funkcji. Za to nudny "nic się
        # nie zmieniło" komunikat pomijamy w trybie automatycznym, żeby nie
        # zasypywać usera powiadomieniem co 5 minut o braku zmian.
        if auto_stopped:
            names_preview = ", ".join(auto_stopped[:5])
            if len(auto_stopped) > 5:
                names_preview += f" i {len(auto_stopped) - 5} więcej"
            InfoBar.success(
                title="Zatrzymano farmienie",
                content=f"Karty się skończyły, zatrzymano: {names_preview}.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        elif not is_automatic:
            InfoBar.info(
                title="Sprawdzono",
                content="Zaktualizowano liczbę pozostałych kart.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _on_badge_progress_error(self, message: str, is_automatic: bool = False) -> None:
        self.check_cards_btn.setEnabled(True)
        self.check_and_queue_btn.setEnabled(True)
        self.badge_progress_bar.setVisible(False)
        # W trybie automatycznym pomijamy dialog/InfoBar błędu - błąd (np.
        # wygasła sesja) i tak nie zniknie sam, a ponawianie tego samego
        # komunikatu co 5 minut byłoby uciążliwe. User i tak zobaczy błąd
        # przy najbliższym RĘCZNYM kliknięciu "Sprawdź pozostałe karty".
        if not is_automatic:
            self.accountProblemDetected.emit(
                f"Steam odrzucił zapisaną sesję: {message}"
            )

    def prompt_resume_saved_queue(self) -> None:
        """Wywoływane raz, przy starcie aplikacji (z MainWindow) - jeśli
        poprzednia sesja zostawiła niepustą kolejkę idle, pyta użytkownika
        czy ją wznowić. Świadomie NIE wznawiamy automatycznie bez pytania:
        user mógł zamknąć aplikację właśnie po to, żeby PRZESTAĆ farmić
        (np. przed wyjazdem, żeby nie zostawiać uruchomionych procesów), a
        ciche wznowienie w tle byłoby zaskakującym, niechcianym zachowaniem."""
        saved_entries = self.manager.load_saved_queue()
        if not saved_entries:
            return

        names_preview = ", ".join(e.name for e in saved_entries[:5])
        if len(saved_entries) > 5:
            names_preview += f" i {len(saved_entries) - 5} więcej"

        box = MessageBox(
            "Wznowić farmienie kart?",
            f"Poprzednia sesja miała {len(saved_entries)} gier w kolejce "
            f"farmienia kart: {names_preview}. Wznowić farmienie?",
            self,
        )
        box.yesButton.setText("Wznów")
        box.cancelButton.setText("Nie wznawiaj")

        if box.exec():
            for entry in saved_entries:
                self.add_game(entry.app_id, entry.name, silent=True)
                if entry.was_paused:
                    self._on_pause(entry.app_id)
                    card = self._cards.get(entry.app_id)
                    if card:
                        job = next(
                            (j for j in self.manager.jobs() if j.app_id == entry.app_id),
                            None,
                        )
                        if job:
                            card.update_state(job)
        else:
            # User świadomie odrzucił wznowienie - czyścimy zapisany plik,
            # żeby przy następnym starcie nie pytać go znowu o tę samą,
            # już raz odrzuconą kolejkę.
            from steamtools.core.config import clear_idle_queue
            clear_idle_queue()

    def has_active_jobs(self) -> bool:
        """Czy w kolejce farmienia jest obecnie jakakolwiek gra (farmiona
        aktywnie albo czekająca w kolejce). Używane przez MainWindow.closeEvent
        do ostrzegania usera przed przerwaniem farmienia przyciskiem X."""
        return bool(self._cards)

    def active_jobs_count(self) -> int:
        """Liczba gier obecnie w kolejce farmienia (aktywnych + oczekujących).
        Używane wyłącznie do treści komunikatu ostrzegawczego w MainWindow -
        has_active_jobs() powyżej wystarcza do samej decyzji tak/nie."""
        return len(self._cards)

    def shutdown(self) -> None:
        # Zapisujemy stan PRZED zatrzymaniem procesów (stop_all czyści
        # self.manager._jobs, więc save_queue po nim zapisałoby pustą
        # kolejkę - kolejność ma tu znaczenie).
        self.manager.save_queue()
        self.manager.stop_all()
