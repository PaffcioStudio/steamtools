"""Widok "Osiągnięcia" dla wybranej gry - odpowiednik SAM.Game/frmMain
z idle_master_extended, ale w stylu Fluent."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QLabel

from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    CaptionLabel,
    BodyLabel,
    CardWidget,
    CheckBox,
    PushButton,
    PrimaryPushButton,
    TransparentToolButton,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
    ScrollArea,
    MessageBox,
    SearchLineEdit,
)

from steamtools.core.steamworks import SteamworksError, AchievementInfo
from steamtools.core.ach_worker import load_achievements, store_achievements

# Powyżej tej liczby jednoczesnych zmian pytamy o potwierdzenie - żeby
# "Zaznacz wszystkie" na grze ze 100 osiągnięciami nie odblokowało wszystkiego
# jednym przypadkowym kliknięciem bez możliwości cofnięcia namysłu.
_CONFIRM_THRESHOLD = 10


class _LoadAchievementsThread(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, app_id: int, parent=None):
        super().__init__(parent)
        self.app_id = app_id

    def run(self) -> None:
        try:
            self.loaded.emit(load_achievements(self.app_id))
        except SteamworksError as exc:
            self.failed.emit(str(exc))


class _StoreAchievementsThread(QThread):
    stored = pyqtSignal(int)  # liczba zapisanych zmian
    failed = pyqtSignal(str)

    def __init__(self, app_id: int, changes: dict, parent=None):
        super().__init__(parent)
        self.app_id = app_id
        self.changes = changes

    def run(self) -> None:
        try:
            ok = store_achievements(self.app_id, self.changes)
        except SteamworksError as exc:
            self.failed.emit(str(exc))
            return
        if ok:
            self.stored.emit(len(self.changes))
        else:
            self.failed.emit("Steam odrzucił zapis statystyk (StoreStats).")


_ICON_SIZE = 48


def icon_pixmap(ach: AchievementInfo) -> QPixmap | None:
    """Ikona osiągnięcia z surowego RGBA (Steamworks) jako QPixmap, albo
    None, gdy gra nie dostarczyła ikony."""
    if not ach.icon_rgba or ach.icon_w <= 0 or ach.icon_h <= 0:
        return None
    if len(ach.icon_rgba) < ach.icon_w * ach.icon_h * 4:
        return None
    # copy() odłącza QImage od bufora bytes, który może zniknąć po zwrocie.
    image = QImage(
        ach.icon_rgba, ach.icon_w, ach.icon_h, ach.icon_w * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()
    return QPixmap.fromImage(image)


class AchievementRow(CardWidget):
    toggled = pyqtSignal(str, bool)  # api_name, new_state

    def __init__(self, ach: AchievementInfo, parent=None):
        super().__init__(parent)
        self.ach = ach
        self.setFixedHeight(72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self.checkbox = CheckBox(self)
        self.checkbox.setChecked(ach.is_achieved)
        self.checkbox.stateChanged.connect(
            lambda state: self.toggled.emit(ach.api_name, state == Qt.CheckState.Checked.value)
        )
        layout.addWidget(self.checkbox)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        pixmap = icon_pixmap(ach)
        if pixmap is not None:
            dpr = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaled(
                int(_ICON_SIZE * dpr), int(_ICON_SIZE * dpr),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self.icon_label.setPixmap(scaled)
        layout.addWidget(self.icon_label)

        text_col = QVBoxLayout()
        title_text = ach.display_name if not ach.hidden or ach.is_achieved else "??? (ukryte)"
        title = BodyLabel(title_text, self)
        sub_text = ach.description if not ach.hidden or ach.is_achieved else ""
        if ach.is_achieved and ach.unlock_time:
            when = datetime.fromtimestamp(ach.unlock_time).strftime("%Y-%m-%d %H:%M")
            sub_text = f"{sub_text}  •  odblokowano {when}" if sub_text else f"Odblokowano {when}"
        subtitle = CaptionLabel(sub_text, self)
        subtitle.setTextColor("#606060", "#c0c0c0")
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, stretch=1)

    def set_checked_silently(self, checked: bool) -> None:
        """Ustawia checkbox bez emitowania toggled -> _on_toggle (używane
        przy 'Zaznacz/Odznacz wszystkie', gdzie zbiorczą zmianę obsługujemy
        osobno, żeby nie robić N wywołań _on_toggle z rzędu)."""
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)


class _EmptyStateWidget(QWidget):
    """Komunikat pokazywany, gdy user wszedł w zakładkę Osiągnięcia bez
    wcześniejszego wyboru gry z Biblioteki."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = IconWidget(FluentIcon.CERTIFICATE, self)
        icon.setFixedSize(64, 64)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)

        title = SubtitleLabel("Wybierz grę, aby zobaczyć osiągnięcia", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = CaptionLabel(
            "Przejdź do zakładki Biblioteka i kliknij „Osiągnięcia” przy "
            "wybranej grze.",
            self,
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setTextColor("#606060", "#c0c0c0")
        layout.addWidget(hint)


class AchievementsView(QWidget):
    """Osadzany widok - MainWindow podmienia jego zawartość, gdy user
    kliknie "Osiągnięcia" na karcie gry w bibliotece."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AchievementsView")
        self.app_id: int | None = None
        self._rows: list[AchievementRow] = []
        self._pending_changes: dict[str, bool] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Stos: strona 0 = pusty stan (bez wybranej gry), strona 1 = realna
        # lista osiągnięć. Domyślnie (przed pierwszym load_game) pokazujemy
        # pusty stan zamiast gołej, pustej tabelki.
        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        self.empty_state = _EmptyStateWidget(self)
        self.stack.addWidget(self.empty_state)

        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        self.title_label = TitleLabel("Osiągnięcia", content)
        header_row.addWidget(self.title_label, stretch=1)

        self.select_all_btn = PushButton(
            "Zaznacz wszystkie", content, FluentIcon.ACCEPT
        )
        self.select_none_btn = PushButton(
            "Odznacz wszystkie", content, FluentIcon.CLOSE
        )
        self.store_btn = PrimaryPushButton("Zapisz zmiany", content, FluentIcon.SAVE)
        self.select_all_btn.clicked.connect(lambda: self._set_all(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all(False))
        self.store_btn.clicked.connect(self._store_changes)
        self.store_btn.setEnabled(False)
        header_row.addWidget(self.select_all_btn)
        header_row.addWidget(self.select_none_btn)
        header_row.addWidget(self.store_btn)
        root.addLayout(header_row)

        self.search = SearchLineEdit(content)
        self.search.setPlaceholderText("Szukaj po nazwie lub opisie…")
        root.addWidget(self.search)

        # Debounce - filtrowanie listy przy każdym naciśniętym znaku byłoby
        # zbędnym obciążeniem, zwłaszcza na grach z setkami osiągnięć.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _: self._filter_timer.start())

        self.progress = IndeterminateProgressBar(content)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.scroll = ScrollArea(content)
        self.scroll.setWidgetResizable(True)
        self.list_widget = QWidget(self.scroll)
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_widget)
        root.addWidget(self.scroll, stretch=1)

        self.stack.addWidget(content)
        self.stack.setCurrentWidget(self.empty_state)

        self._thread: _LoadAchievementsThread | None = None
        self._store_thread: _StoreAchievementsThread | None = None

    def load_game(self, app_id: int, name: str) -> None:
        self.app_id = app_id
        self.title_label.setText(f"Osiągnięcia - {name}")
        self._pending_changes.clear()
        self.store_btn.setEnabled(False)
        self.stack.setCurrentIndex(1)

        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)

        for row in self._rows:
            row.setParent(None)
        self._rows.clear()

        self.progress.setVisible(True)
        self._thread = _LoadAchievementsThread(app_id, self)
        self._thread.loaded.connect(self._on_loaded)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_loaded(self, achievements: list[AchievementInfo]) -> None:
        self.progress.setVisible(False)
        for ach in achievements:
            row = AchievementRow(ach, self.list_widget)
            row.toggled.connect(self._on_toggle)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)

        has_achievements = bool(achievements)
        self.select_all_btn.setEnabled(has_achievements)
        self.select_none_btn.setEnabled(has_achievements)

        if not has_achievements:
            InfoBar.info(
                title="Brak osiągnięć",
                content="Ta gra nie ma żadnych osiągnięć do wyświetlenia.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )

    def _apply_filter(self) -> None:
        text = self.search.text().lower().strip()
        for row in self._rows:
            if not text:
                row.setVisible(True)
                continue
            # Filtrujemy po tym co FAKTYCZNIE widać na ekranie (nazwa może
            # być zamaskowana jako "??? (ukryte)" dla nieodblokowanych,
            # ukrytych osiągnięć) - nie po surowych danych z AchievementInfo.
            # Filtrowanie po surowej, ukrytej treści pozwalałoby odkryć
            # istnienie/opis ukrytego osiągnięcia (potencjalny spoiler)
            # samym wpisywaniem słów w wyszukiwarkę, czego chcemy uniknąć.
            ach = row.ach
            visible_name = ach.display_name if not ach.hidden or ach.is_achieved else "??? (ukryte)"
            visible_desc = ach.description if not ach.hidden or ach.is_achieved else ""
            haystack = f"{visible_name} {visible_desc}".lower()
            row.setVisible(text in haystack)

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        InfoBar.error(
            title="Błąd Steamworks",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )

    def _on_toggle(self, api_name: str, new_state: bool) -> None:
        self._pending_changes[api_name] = new_state
        self.store_btn.setEnabled(bool(self._pending_changes))

    def _set_all(self, checked: bool) -> None:
        """Zaznacza lub odznacza wszystkie osiągnięcia naraz. Przy wielu
        pozycjach (> _CONFIRM_THRESHOLD) prosi o potwierdzenie, żeby jedno
        kliknięcie nie odblokowało/zablokowało np. 50 osiągnięć bez namysłu."""
        if not self._rows:
            return

        # Filtrujemy tylko te, które faktycznie zmienią stan - "Zaznacz
        # wszystkie" na grze gdzie połowa już jest odblokowana powinno
        # pytać o realną liczbę zmian, nie o całkowitą liczbę osiągnięć.
        # WAŻNE: porównujemy z aktualnym stanem checkboxa na ekranie
        # (row.checkbox.isChecked()), nie z oryginalnym ach.is_achieved z
        # serwera - user mógł już poklikać część osiągnięć ręcznie przed
        # kliknięciem "Zaznacz wszystkie", i to musi być uwzględnione.
        rows_to_change = [
            row for row in self._rows if row.checkbox.isChecked() != checked
        ]
        if not rows_to_change:
            InfoBar.info(
                title="Brak zmian",
                content="Wszystkie osiągnięcia mają już ten stan.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            return

        if len(rows_to_change) > _CONFIRM_THRESHOLD:
            action = "odblokować" if checked else "zablokować"
            box = MessageBox(
                "Potwierdź zbiorczą zmianę",
                f"Zamierzasz {action} {len(rows_to_change)} osiągnięć naraz. "
                f"Kontynuować?",
                self,
            )
            box.yesButton.setText("Tak")
            box.cancelButton.setText("Anuluj")
            if not box.exec():
                return

        for row in rows_to_change:
            row.set_checked_silently(checked)
            self._pending_changes[row.ach.api_name] = checked

        self.store_btn.setEnabled(bool(self._pending_changes))

    def _store_changes(self) -> None:
        if self.app_id is None or not self._pending_changes:
            return
        if self._store_thread is not None and self._store_thread.isRunning():
            return
        self.store_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._store_thread = _StoreAchievementsThread(
            self.app_id, dict(self._pending_changes), self
        )
        self._store_thread.stored.connect(self._on_stored)
        self._store_thread.failed.connect(self._on_store_failed)
        self._store_thread.start()

    def _on_stored(self, count: int) -> None:
        self.progress.setVisible(False)
        InfoBar.success(
            title="Zapisano",
            content=f"Zaktualizowano {count} osiągnięć.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
        self._pending_changes.clear()
        self.store_btn.setEnabled(False)

    def _on_store_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.store_btn.setEnabled(bool(self._pending_changes))
        InfoBar.error(
            title="Błąd zapisu",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )
