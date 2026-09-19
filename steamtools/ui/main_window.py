"""Główne okno aplikacji: FluentWindow z sidebarem, analogiczny w stylu
do innych projektów (nowoczesny navigation rail zamiast klasycznego menu
WinForms z idle_master_extended / SAM)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QThread
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from qfluentwidgets import (
    FluentWindow,
    FluentIcon,
    NavigationItemPosition,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    MessageBox,
    SubtitleLabel,
    BodyLabel,
    PrimaryPushButton,
)

from steamtools.core.steamworks import is_steam_running
from steamtools.ui.views.library_view import LibraryView
from steamtools.ui.views.achievements_view import AchievementsView
from steamtools.ui.views.idle_view import IdleView
from steamtools.ui.views.account_view import AccountView
from steamtools.ui.views.settings_view import SettingsView, config
from steamtools.ui.views.about_view import AboutView

_ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _load_app_icon() -> QIcon:
    """Buduje QIcon z pełnego zestawu wygenerowanych rozdzielczości
    (steamtools-16.png .. steamtools-512.png) - Qt samo wybierze najlepiej
    pasujący rozmiar zależnie od kontekstu (pasek tytułu, alt-tab, taskbar
    przy różnych DPI), zamiast skalować jeden obrazek w locie."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        path = _ICONS_DIR / f"steamtools-{size}.png"
        if path.exists():
            icon.addFile(str(path))
    return icon


class _ClosingWhileIdlingDialog(MessageBoxBase):
    """Ostrzeżenie pokazywane przy X, gdy trwa farmienie kart, a "Zamykaj
    do zasobnika systemowego" jest WYŁĄCZONE - w tej konfiguracji zwykłe
    zamknięcie okna ubiłoby proces i przerwało farmienie bez ostrzeżenia,
    co przy sesjach trwających nawet godzinami byłoby frustrujące. Trzy
    opcje zamiast standardowych Tak/Nie z MessageBox, więc budujemy to na
    MessageBoxBase zamiast gotowego MessageBoxa."""

    # Wartości zwracane przez exec_choice() - odróżniają, którą z trzech
    # opcji wybrał user (albo zamknął dialog krzyżykiem/Esc = "cancel").
    HIDE_TO_TRAY = "hide"
    QUIT = "quit"
    CANCEL = "cancel"

    def __init__(self, active_games_count: int, tray_available: bool, parent=None):
        super().__init__(parent)
        self._result = self.CANCEL

        title = SubtitleLabel("Trwa farmienie kart", self)
        body = BodyLabel(
            f"Aktualnie farmisz karty w {active_games_count} "
            f"{'grze' if active_games_count == 1 else 'grach'}. Zamknięcie "
            "programu przerwie ten proces. Co chcesz zrobić?",
            self,
        )
        body.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(body)

        # Trzy realne opcje zamiast domyślnych yes/cancel - podmieniamy
        # cancelButton na "Anuluj" (zostań w programie), yesButton na
        # "Przerwij i zamknij" (świadome ubicie farmienia), i dokładamy
        # trzeci, dodatkowy przycisk "Ukryj w tray" jako najbezpieczniejszą,
        # zalecaną opcję - stąd na pierwszym miejscu w layoutcie. Ale tylko
        # gdy tray faktycznie jest dostępny w danym środowisku (część
        # gołych WM na Linuksie go nie udostępnia) - inaczej ta opcja
        # byłaby atrapą, która nic by nie zrobiła.
        if tray_available:
            self.hide_button = PrimaryPushButton("Ukryj w tray", self)
            self.hide_button.clicked.connect(self._on_hide_clicked)
            self.buttonLayout.insertWidget(0, self.hide_button, 1, Qt.AlignmentFlag.AlignVCenter)
            self.yesButton.setText("Przerwij i zamknij")
        else:
            self.yesButton.setText("Zamknij mimo to")

        # Czerwone tło zamiast domyślnego niebieskiego motywu Fluent - to
        # jedyna z trzech opcji, która realnie przerywa farmienie, więc ma
        # wyglądać wyraźnie inaczej niż "Ukryj w tray" (bezpieczna, zalecana
        # opcja). setStyleSheet() na pojedynczym widgecie CAŁKOWICIE
        # zastępuje globalny QSS motywu dla tego przycisku (nie scala się z
        # nim) - dlatego oprócz koloru trzeba jawnie powtórzyć border-radius/
        # padding/border, inaczej przycisk traci zaokrąglone rogi i wygląda
        # niespójnie obok sąsiednich, wciąż w pełni ostylowanych przycisków
        # (dokładnie to, co widać na pierwszej, wadliwej wersji tej poprawki).
        self.yesButton.setObjectName("dangerButton")
        self.yesButton.setStyleSheet(
            "PushButton#dangerButton {"
            "  color: white;"
            "  background-color: #c42b1c;"
            "  border: 1px solid #c42b1c;"
            "  border-radius: 5px;"
            "  padding: 5px 12px 6px 12px;"
            "  outline: none;"
            "}"
            "PushButton#dangerButton:hover {"
            "  background-color: #d13438;"
            "  border: 1px solid #d13438;"
            "}"
            "PushButton#dangerButton:pressed {"
            "  color: rgba(255, 255, 255, 0.63);"
            "  background-color: #a52016;"
            "  border: 1px solid #a52016;"
            "}"
        )

        self.yesButton.clicked.disconnect()
        self.yesButton.clicked.connect(self._on_quit_clicked)

        self.cancelButton.setText("Anuluj")

        self.widget.setMinimumWidth(420)

    def _on_hide_clicked(self) -> None:
        self._result = self.HIDE_TO_TRAY
        self.accept()

    def _on_quit_clicked(self) -> None:
        self._result = self.QUIT
        self.accept()

    def exec_choice(self) -> str:
        """Uruchamia dialog modalnie i zwraca jedną z HIDE_TO_TRAY / QUIT /
        CANCEL - CANCEL także gdy user zamknął dialog krzyżykiem/Esc, bo
        wtedy accept() nigdy się nie wykonuje i self._result zostaje przy
        swojej wartości domyślnej."""
        self.exec()
        return self._result


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamTools")
        self.setWindowIcon(_load_app_icon())
        self.resize(1080, 720)

        # Flaga ustawiana przez menu kontekstowe traya ("Zamknij program"),
        # żeby odróżnić świadome zakończenie aplikacji od zwykłego kliknięcia
        # w X - closeEvent sprawdza ją, zanim zdecyduje, czy schować okno do
        # traya, czy pozwolić oknu faktycznie się zamknąć.
        self._force_quit = False
        self._tray_icon = self._build_tray_icon()

        self.library_view = LibraryView(self)
        self.achievements_view = AchievementsView(self)
        self.idle_view = IdleView(self)
        self.account_view = AccountView(self)
        self.settings_view = SettingsView(self)
        self.about_view = AboutView(self)

        self.addSubInterface(
            self.library_view, FluentIcon.LIBRARY, "Biblioteka"
        )
        self.addSubInterface(
            self.achievements_view, FluentIcon.CERTIFICATE, "Osiągnięcia"
        )
        self.addSubInterface(
            self.idle_view, FluentIcon.GAME, "Farma kart"
        )
        self.addSubInterface(
            self.about_view,
            FluentIcon.INFO,
            "Informacje",
            position=NavigationItemPosition.BOTTOM,
        )
        # Między "Informacje" a "Ustawienia" - kolejność wywołań
        # addSubInterface() decyduje o kolejności w sidebarze przy tej
        # samej pozycji (BOTTOM). Zakładka "Konto" była wcześniej schowana
        # jako sekcja na dole Ustawień, gdzie praktycznie nikt jej nie
        # odkrywał - jako osobna, widoczna pozycja w sidebarze jest od razu
        # zauważalna przy pierwszym uruchomieniu.
        self.addSubInterface(
            self.account_view,
            FluentIcon.PEOPLE,
            "Konto",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settings_view,
            FluentIcon.SETTING,
            "Ustawienia",
            position=NavigationItemPosition.BOTTOM,
        )

        # Kliknięcie "Osiągnięcia" na karcie gry -> przełącz zakładkę i
        # od razu załaduj dane tej gry.
        self.library_view.achievementsRequested.connect(self._open_achievements)
        self.library_view.idleRequested.connect(self._open_idle)

        # Powiadomienia na pulpicie o farmieniu kart (patrz Ustawienia ->
        # Zachowanie) - IdleView nie wie nic o trayu/oknie, więc tylko
        # emituje sygnały, a MainWindow (który ma dostęp do _tray_icon)
        # decyduje, czy faktycznie pokazać powiadomienie, sprawdzając
        # config.notify_*. Rozdzielenie odpowiedzialności: IdleView zna
        # WYNIK sprawdzenia kart, MainWindow zna UI powiadomień.
        self.idle_view.gameCardsExhausted.connect(self._on_game_cards_exhausted)
        self.idle_view.allGamesFinished.connect(self._on_all_games_finished)
        self.idle_view.accountProblemDetected.connect(self._on_account_problem)

        # Przycisk "Otwórz" w sekcji "O aplikacji" (Ustawienia) -> przełącz
        # na pełną zakładkę Informacje zamiast dublować jej zawartość tutaj.
        self.settings_view.openAboutRequested.connect(
            lambda: self.switchTo(self.about_view)
        )

        # Status klienta Steam - sprawdzany od razu po starcie i cyklicznie,
        # bo Steam może zostać zamknięty/uruchomiony w trakcie pracy z appką
        # (a Steamworks nic nie zrobi bez żywego klienta).
        self._steam_was_running: bool | None = None
        self._steam_status_timer = QTimer(self)
        self._steam_status_timer.setInterval(5000)
        self._steam_status_timer.timeout.connect(self._check_steam_status)
        self._steam_status_timer.start()
        self._check_steam_status(initial=True)

        # Odłożone na kolejny cykl event loopa - MessageBox (wywoływany w
        # środku) wymaga w pełni zainicjalizowanej geometrii okna rodzica,
        # a to nie jest jeszcze pewne w trakcie samego __init__.
        QTimer.singleShot(0, self.idle_view.prompt_resume_saved_queue)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    def _shutdown_background_threads(self) -> None:
        """Czeka na zakończenie wszystkich w tym momencie działających
        wątków sieciowych/Steamworks w widokach, zanim program się
        faktycznie zamknie - bez tego, jeśli user zamknie okno w trakcie
        trwającego requestu (sprawdzanie kart, ładowanie osiągnięć,
        walidacja sesji, sprawdzanie aktualizacji), Python może zniszczyć
        obiekt QThread zanim wątek w C++ zdąży się zakończyć, co Qt zgłasza
        jako "QThread: Destroyed while thread is still running" - ostrzeżenie
        nieszkodliwe dla danych (te wątki tylko odczytują, niczego nie
        zapisują), ale hałaśliwe w logach i formalnie niezdefiniowane
        zachowanie samego Qt. Każdy z tych atrybutów istnieje tylko
        czasowo, dokładnie na czas trwania danego requestu (patrz
        odpowiednie widoki) - stąd getattr z None jako domyślną wartością
        zamiast zakładania, że atrybut zawsze jest obecny.
        Limit 3s na wątek: to zapytania sieciowe z własnym timeoutem
        (fetch_badge_progress/urllib), więc w najgorszym razie zamknięcie
        programu wydłuża się o ich czas oczekiwania, ale nigdy nie wisi
        w nieskończoność."""
        candidates = [
            getattr(self.account_view, "_validate_thread", None),
            getattr(self.achievements_view, "_thread", None),
            getattr(self.idle_view, "_badge_thread", None),
            getattr(self.library_view, "_badge_thread", None),
            getattr(self.about_view, "_update_thread", None),
        ]
        for thread in candidates:
            if isinstance(thread, QThread) and thread.isRunning():
                thread.quit()
                thread.wait(3000)

    def _check_steam_status(self, initial: bool = False) -> None:
        running = is_steam_running()
        if running == self._steam_was_running:
            return

        if not running:
            InfoBar.warning(
                title="Steam nie jest uruchomiony",
                content="Osiągnięcia i farmienie kart wymagają uruchomionego "
                "i zalogowanego klienta Steam.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        elif not initial and self._steam_was_running is False:
            InfoBar.success(
                title="Steam wykryty",
                content="Klient Steam jest teraz uruchomiony.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

        self._steam_was_running = running

    def _build_tray_icon(self) -> QSystemTrayIcon:
        """Ikonka w tray - ta sama grafika co ikona okna/aplikacji (patrz
        _load_app_icon), żeby program wyglądał spójnie na pasku zadań i
        w zasobniku. Menu kontekstowe celowo minimalne: tylko przywrócenie
        okna i pełne zamknięcie programu - to jedyne dwie akcje, które nie
        są dostępne w żaden inny sposób, gdy okno jest schowane."""
        tray = QSystemTrayIcon(_load_app_icon(), self)
        tray.setToolTip("SteamTools")

        # Referencje do menu i akcji trzymane jako atrybuty obiektu -
        # bez tego Python może skasować te obiekty (GC), mimo że
        # setContextMenu()/tray je "trzyma" tylko od strony C++/Qt, co
        # prowadzało do niestabilnego, zawieszającego się zachowania przy
        # próbie kliknięcia w menu lub zamknięcia programu.
        self._tray_menu = QMenu()
        self._tray_open_action = QAction("Otwórz okno", self._tray_menu)
        self._tray_open_action.triggered.connect(self._restore_from_tray)
        self._tray_menu.addAction(self._tray_open_action)

        self._tray_menu.addSeparator()

        self._tray_quit_action = QAction("Zamknij program", self._tray_menu)
        self._tray_quit_action.triggered.connect(self._quit_from_tray)
        self._tray_menu.addAction(self._tray_quit_action)

        tray.setContextMenu(self._tray_menu)
        tray.activated.connect(self._on_tray_activated)
        return tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Dwuklik przywraca okno. Pojedyncze kliknięcie (Trigger) celowo NIE
        # przywraca - na wielu środowiskach Linuksowych (KDE/GNOME) samo
        # kliknięcie w ikonkę traya od razu otwiera menu kontekstowe, więc
        # dodatkowa akcja na Trigger byłaby tam po prostu martwym kodem, a
        # na Windowsie mogłaby prowadzić do przypadkowego przywracania okna
        # przy próbie kliknięcia w menu.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_from_tray(self) -> None:
        # setQuitOnLastWindowClosed(False) (patrz app.py) jest tu kluczowe -
        # bez niego zamknięcie ostatniego okna kończyłoby aplikację, co
        # łamałoby całą ideę chowania do tray. Ale to oznacza, że samo
        # self.close() (zamknięcie okna) już NIE wystarcza do faktycznego
        # zakończenia procesu - trzeba jawnie zażądać zamknięcia całej
        # aplikacji przez QApplication.quit(), inaczej event loop żyje
        # dalej "bez okna", tylko z ikonką w tray, i program wisi w tle
        # aż do SIGKILL/Ctrl+C.
        self._force_quit = True
        self.idle_view.shutdown()
        self._shutdown_background_threads()
        self._tray_icon.hide()
        QApplication.instance().quit()

    def _open_achievements(self, app_id: int, name: str) -> None:
        self.achievements_view.load_game(app_id, name)
        self.switchTo(self.achievements_view)

    def _open_idle(self, app_id: int, name: str) -> None:
        self.idle_view.add_game(app_id, name)
        self.switchTo(self.idle_view)

    def _on_game_cards_exhausted(self, name: str) -> None:
        if not config.notify_game_cards_exhausted.value:
            return
        self._show_desktop_notification(
            "Karty wyfarmione",
            f"{name}: wszystkie karty zostały zdobyte, farmienie zatrzymane.",
        )

    def _on_all_games_finished(self) -> None:
        if not config.notify_all_games_finished.value:
            return
        self._show_desktop_notification(
            "Farmienie zakończone",
            "Wszystkie gry w kolejce zostały wyfarmione - kolejka jest pusta.",
        )

    def _on_account_problem(self, message: str) -> None:
        """User RĘCZNIE próbował sprawdzić/dodać gry po kartach, ale konto
        Steam Community nie jest skonfigurowane albo sesja jest nieważna
        (patrz IdleView.accountProblemDetected). Zamiast gołego InfoBara -
        dialog z bezpośrednią drogą do naprawy, bo "coś nie działa, idź
        sam poszukaj gdzie" jest gorszym doświadczeniem niż jeden klik do
        właściwej zakładki."""
        box = MessageBox(
            "Problem z kontem Steam",
            message,
            self,
        )
        box.yesButton.setText("Zarządzaj kontem")
        box.cancelButton.setText("Zamknij")
        if box.exec():
            self.switchTo(self.account_view)

    def _show_desktop_notification(self, title: str, message: str) -> None:
        """Pokazuje natywne powiadomienie systemowe przez ikonkę traya -
        działa niezależnie od tego, czy okno główne jest w danym momencie
        widoczne czy schowane (patrz closeEvent/minimize_to_tray), bo
        QSystemTrayIcon.showMessage() nie wymaga widocznego okna, tylko
        samego traya. Bez dostępnego traya (część minimalnych WM na
        Linuksie go nie udostępnia - patrz QSystemTrayIcon.isSystemTrayAvailable
        w closeEvent) po cichu nic nie pokazujemy zamiast się wywalać."""
        if not QSystemTrayIcon.isSystemTrayAvailable() or not self._tray_icon.isVisible():
            return
        self._tray_icon.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        # Chowanie do tray ma sens tylko gdy: ustawienie jest włączone, tray
        # faktycznie jest dostępny w danym środowisku (np. niektóre goły
        # WM na Linuksie go nie udostępniają) i to nie jest świadome
        # "Zamknij program" z menu traya (_force_quit). W każdym innym
        # przypadku - normalne zamknięcie, tak jak dotychczas.
        if (
            not self._force_quit
            and config.minimize_to_tray.value
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            event.ignore()
            self.hide()
            return

        # Zamykanie-do-tray jest WYŁĄCZONE (albo tray niedostępny/force_quit)
        # - w tej sytuacji zwykły X normalnie ubija cały proces natychmiast.
        # Jeśli akurat coś się farmi, ostrzegamy zamiast cicho przerywać:
        # user mógł kliknąć X odruchowo, nie zdając sobie sprawy że straci
        # postęp farmienia tej sesji (do zdobycia karty trzeba farmić od
        # nowa od zera po restarcie, bo Steam liczy czas w grze na żywo).
        if not self._force_quit and self.idle_view.has_active_jobs():
            active_count = self.idle_view.active_jobs_count()
            tray_available = QSystemTrayIcon.isSystemTrayAvailable()
            dialog = _ClosingWhileIdlingDialog(active_count, tray_available, self)
            choice = dialog.exec_choice()

            if choice == _ClosingWhileIdlingDialog.CANCEL:
                event.ignore()
                return
            if choice == _ClosingWhileIdlingDialog.HIDE_TO_TRAY and tray_available:
                event.ignore()
                self.hide()
                return
            # choice == QUIT (albo HIDE_TO_TRAY bez dostępnego traya, co i
            # tak nie powinno się zdarzyć skoro przycisk wtedy nie istnieje)
            # -> user świadomie potwierdził przerwanie, lecimy dalej do
            # zamknięcia poniżej.

        # app.py ustawia globalnie setQuitOnLastWindowClosed(False)
        # (wymagane, żeby zamknięcie okna przy WŁĄCZONYM "Zamykaj do tray"
        # NIE kończyło całego procesu) - efektem ubocznym jest to, że samo
        # zamknięcie okna (super().closeEvent poniżej) już NIE wystarcza do
        # zakończenia programu w TEJ gałęzi (świadome zamknięcie): bez
        # jawnego QApplication.quit() proces zostawałby żywy w tle z
        # ukrytym oknem, a ikonka w tray (nigdy nieukryta) sprawiałaby
        # wrażenie że program "wcale się nie zamknął" - dokładnie to samo,
        # co już rozwiązuje _quit_from_tray() dla ścieżki z menu traya.
        self.idle_view.shutdown()
        self._shutdown_background_threads()
        self._tray_icon.hide()
        super().closeEvent(event)
        QApplication.instance().quit()
