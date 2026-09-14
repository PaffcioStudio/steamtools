"""Główne okno aplikacji: FluentWindow z sidebarem, analogiczny w stylu
do innych projektów (nowoczesny navigation rail zamiast klasycznego menu
WinForms z idle_master_extended / SAM)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from qfluentwidgets import FluentWindow, FluentIcon, NavigationItemPosition, InfoBar, InfoBarPosition

from steamtools.core.steamworks import is_steam_running
from steamtools.ui.views.library_view import LibraryView
from steamtools.ui.views.achievements_view import AchievementsView
from steamtools.ui.views.idle_view import IdleView
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
        self._tray_icon.hide()
        QApplication.instance().quit()

    def _open_achievements(self, app_id: int, name: str) -> None:
        self.achievements_view.load_game(app_id, name)
        self.switchTo(self.achievements_view)

    def _open_idle(self, app_id: int, name: str) -> None:
        self.idle_view.add_game(app_id, name)
        self.switchTo(self.idle_view)

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

        self.idle_view.shutdown()
        super().closeEvent(event)
