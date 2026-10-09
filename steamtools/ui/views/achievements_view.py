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
    ComboBox,
)

from steamtools.core.steamworks import SteamworksError, AchievementInfo
from steamtools.core.errors import friendly_error
from steamtools.core.ach_worker import load_achievements, store_achievements

# Powyżej tej liczby jednoczesnych zmian pytamy o potwierdzenie - żeby
# "Zaznacz wszystkie" na grze ze 100 osiągnięciami nie odblokowało wszystkiego
# jednym przypadkowym kliknięciem bez możliwości cofnięcia namysłu.
_CONFIRM_THRESHOLD = 10


class _LoadAchievementsThread(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str, str)  # tytuł, treść (przyjazne, patrz core/errors.py)

    def __init__(self, app_id: int, parent=None):
        super().__init__(parent)
        self.app_id = app_id

    def run(self) -> None:
        try:
            self.loaded.emit(load_achievements(self.app_id))
        except SteamworksError as exc:
            self.failed.emit(*friendly_error(exc))


class _StoreAchievementsThread(QThread):
    stored = pyqtSignal(int)  # liczba zapisanych zmian
    failed = pyqtSignal(str, str)

    def __init__(self, app_id: int, changes: dict, parent=None):
        super().__init__(parent)
        self.app_id = app_id
        self.changes = changes

    def run(self) -> None:
        try:
            ok = store_achievements(self.app_id, self.changes)
        except SteamworksError as exc:
            title, content = friendly_error(exc)
            self.failed.emit("Błąd zapisu" if exc.kind == "generic" else title, content)
            return
        if ok:
            self.stored.emit(len(self.changes))
        else:
            self.failed.emit("Błąd zapisu", "Steam odrzucił zapis statystyk (StoreStats).")


_ICON_SIZE = 48

# Kolejność odpowiada indeksom w ComboBoxach - _matches_filter/_sort_key
# rozróżniają tryby po numerze, więc nową pozycję dopisuj na końcu.
_FILTER_MODES = ["Wszystkie", "Odblokowane", "Zablokowane", "Ukryte", "Zmienione (do zapisu)"]
_SORT_MODES = ["Kolejność gry", "Nazwa A-Z", "Najnowsze odblokowane", "Zablokowane najpierw"]


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
        self.matched = True  # czy przechodzi aktualny filtr/wyszukiwanie
        self.order = 0
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

        search_row = QHBoxLayout()
        self.search = SearchLineEdit(content)
        self.search.setPlaceholderText("Szukaj po nazwie lub opisie…")
        search_row.addWidget(self.search, stretch=1)

        self.filter_combo = ComboBox(content)
        self.filter_combo.addItems(_FILTER_MODES)
        self.filter_combo.setToolTip("Pokaż tylko wybrane osiągnięcia")
        self.sort_combo = ComboBox(content)
        self.sort_combo.addItems(_SORT_MODES)
        self.sort_combo.setToolTip("Kolejność osiągnięć")
        self.undo_btn = PushButton("Cofnij zmiany", content, FluentIcon.CANCEL)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo_changes)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.sort_combo.currentIndexChanged.connect(self._apply_sort)
        search_row.addWidget(self.filter_combo)
        search_row.addWidget(self.sort_combo)
        search_row.addWidget(self.undo_btn)
        root.addLayout(search_row)

        self.summary_label = CaptionLabel("", content)
        self.summary_label.setTextColor("#606060", "#c0c0c0")
        root.addWidget(self.summary_label)

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
        for combo in (self.filter_combo, self.sort_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.undo_btn.setEnabled(False)
        self.summary_label.setText("")

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
        for index, ach in enumerate(achievements):
            row = AchievementRow(ach, self.list_widget)
            row.order = index  # kolejność zwrócona przez grę (sortowanie "domyślne")
            row.toggled.connect(self._on_toggle)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self._rows.append(row)
        self._update_summary()

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

    def _matches_filter(self, row: AchievementRow) -> bool:
        mode = self.filter_combo.currentIndex()
        checked = row.checkbox.isChecked()
        if mode == 1:
            return checked
        if mode == 2:
            return not checked
        if mode == 3:
            return row.ach.hidden
        if mode == 4:
            return row.ach.api_name in self._pending_changes
        return True

    def _matches_text(self, row: AchievementRow, text: str) -> bool:
        if not text:
            return True
        # Filtrujemy po tym co FAKTYCZNIE widać na ekranie (nazwa może
        # być zamaskowana jako "??? (ukryte)" dla nieodblokowanych,
        # ukrytych osiągnięć) - nie po surowych danych z AchievementInfo.
        # Filtrowanie po surowej, ukrytej treści pozwalałoby odkryć
        # istnienie/opis ukrytego osiągnięcia (potencjalny spoiler)
        # samym wpisywaniem słów w wyszukiwarkę, czego chcemy uniknąć.
        ach = row.ach
        visible_name = ach.display_name if not ach.hidden or ach.is_achieved else "??? (ukryte)"
        visible_desc = ach.description if not ach.hidden or ach.is_achieved else ""
        return text in f"{visible_name} {visible_desc}".lower()

    def _apply_filter(self, *_args) -> None:
        text = self.search.text().lower().strip()
        for row in self._rows:
            # Własna flaga zamiast isHidden(): tuż po dodaniu do layoutu Qt
            # zgłasza dziecko jako ukryte, zanim rodzic je faktycznie pokaże.
            row.matched = self._matches_text(row, text) and self._matches_filter(row)
            row.setVisible(row.matched)
        self._update_summary()

    def _sort_key(self, row: AchievementRow):
        mode = self.sort_combo.currentIndex()
        if mode == 1:
            return row.ach.display_name.lower()
        if mode == 2:
            # odblokowane od najnowszego, zablokowane na końcu (w kolejności gry)
            return (0, -row.ach.unlock_time, row.order) if row.ach.is_achieved else (1, 0, row.order)
        if mode == 3:
            return (0, row.order) if not row.checkbox.isChecked() else (1, row.order)
        return row.order

    def _apply_sort(self, *_args) -> None:
        ordered = sorted(self._rows, key=self._sort_key)
        for row in ordered:
            self.list_layout.removeWidget(row)
        for position, row in enumerate(ordered):
            self.list_layout.insertWidget(position, row)

    def _update_summary(self) -> None:
        total = len(self._rows)
        if not total:
            self.summary_label.setText("")
            return
        unlocked = sum(1 for r in self._rows if r.checkbox.isChecked())
        shown = sum(1 for r in self._rows if r.matched)
        text = f"Odblokowano {unlocked} z {total}"
        if shown != total:
            text += f"  •  widocznych: {shown}"
        if self._pending_changes:
            text += f"  •  niezapisanych zmian: {len(self._pending_changes)}"
        self.summary_label.setText(text)

    def _after_state_change(self) -> None:
        """Stan checkboxów/zmian oczekujących się zmienił - odśwież to, co
        od niego zależy (filtr stanu, sortowanie po stanie, licznik)."""
        self.undo_btn.setEnabled(bool(self._pending_changes))
        if self.filter_combo.currentIndex() in (1, 2, 4):
            self._apply_filter()
        else:
            self._update_summary()

    def _undo_changes(self) -> None:
        """Przywraca stan sprzed edycji (to, co faktycznie jest na koncie)."""
        for row in self._rows:
            row.set_checked_silently(row.ach.is_achieved)
        self._pending_changes.clear()
        self.store_btn.setEnabled(False)
        self._after_state_change()

    def _on_failed(self, title: str, content: str) -> None:
        self.progress.setVisible(False)
        InfoBar.error(
            title=title,
            content=content,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )

    def _on_toggle(self, api_name: str, new_state: bool) -> None:
        # Wrócenie checkboxa do stanu z konta nie jest już "zmianą".
        row = next((r for r in self._rows if r.ach.api_name == api_name), None)
        if row is not None and row.ach.is_achieved == new_state:
            self._pending_changes.pop(api_name, None)
        else:
            self._pending_changes[api_name] = new_state
        self.store_btn.setEnabled(bool(self._pending_changes))
        self._after_state_change()

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
        # Działa na widocznych wierszach: po zawężeniu filtrem/wyszukiwarką
        # "Zaznacz wszystkie" dotyczy tego, co user widzi na liście.
        rows_to_change = [
            row for row in self._rows
            if row.matched and row.checkbox.isChecked() != checked
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
            if row.ach.is_achieved == checked:
                self._pending_changes.pop(row.ach.api_name, None)
            else:
                self._pending_changes[row.ach.api_name] = checked

        self.store_btn.setEnabled(bool(self._pending_changes))
        self._after_state_change()

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
        # Zapisany stan jest teraz stanem "z konta" - "Cofnij zmiany" i
        # maskowanie ukrytych osiągnięć mają się odnosić do niego.
        saved = self._store_thread.changes if self._store_thread is not None else {}
        for row in self._rows:
            if row.ach.api_name in saved:
                row.ach.is_achieved = saved[row.ach.api_name]
        self._pending_changes.clear()
        self.store_btn.setEnabled(False)
        self._after_state_change()

    def _on_store_failed(self, title: str, content: str) -> None:
        self.progress.setVisible(False)
        self.store_btn.setEnabled(bool(self._pending_changes))
        InfoBar.error(
            title=title,
            content=content,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )
