"""Punkt wejścia SteamTools."""

from __future__ import annotations

import multiprocessing as mp
import sys

from PyQt6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme

from steamtools.ui.main_window import MainWindow


def _qt_message_filter(msg_type: QtMsgType, context, message: str) -> None:
    """Wycisza nieszkodliwe ostrzeżenie platformy Wayland o braku wsparcia
    dla ustawiania przezroczystości okna. Pochodzi z animacji przejść między
    stronami w PyQt6-Frameless-Window/qfluentwidgets - kosmetyczny fade
    działa nadal poprawnie, po prostu kompozytor KDE/Wayland ignoruje
    natywne ustawienie opacity na tym typie okna. Wszystkie inne komunikaty
    przepuszczamy normalnie na stderr, żeby nie ukryć prawdziwych błędów."""
    if "does not support setting window opacity" in message:
        return
    sys.stderr.write(message + "\n")


def main() -> int:
    qInstallMessageHandler(_qt_message_filter)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("SteamTools")

    # Bez tego Qt zamknąłby cały event loop (i tym samym program) w
    # momencie schowania okna do tray - z jego perspektywy "ostatnie okno"
    # właśnie zostało zamknięte, mimo że aplikacja ma dalej żyć w
    # zasobniku. Ikonka traya (main_window.py) sama decyduje kiedy proces
    # faktycznie się kończy (menu "Zamknij program").
    app.setQuitOnLastWindowClosed(False)

    setTheme(Theme.AUTO)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    # KRYTYCZNE dla spakowanej binarki (PyInstaller --onedir, patrz
    # packaging/steamtools.spec i build_deb.sh): każdy proces idle
    # (steamtools/core/idler.py -> IdleManager, mp.get_context("spawn"))
    # to nowy proces potomny, który - w binarce PyInstaller, gdzie NIE MA
    # osobnego "czystego" interpretera python3, tylko jeden plik
    # wykonywalny będący jednocześnie całym programem - od nowa wchodzi w
    # ten sam __main__. Bez freeze_support() ten nowy proces potomny
    # odpalał całą aplikację GUI (main()) od zera zamiast tylko lekkiego
    # _idle_worker, co dawało tyle dodatkowych okien SteamTools ile gier
    # farmionych naraz. Uruchomione przez zwykłe `python3 app.py`
    # (run.sh) tego problemu nie było, bo tam spawn używa prawdziwego
    # interpretera Pythona, a nie samej binarki. freeze_support() MUSI
    # być pierwszą linią wykonywaną w __main__, przed jakąkolwiek inną
    # logiką (stąd import multiprocessing na samej górze pliku, ale samo
    # wywołanie tutaj, nie na poziomie modułu).
    mp.freeze_support()
    sys.exit(main())

