"""Widok "Biblioteka" - lista zainstalowanych gier, punkt wejścia do
achievementów i idle dla konkretnej gry.

Uwaga wydajnościowa: biblioteki rzędu 100-200+ gier (typowe przy kilku
dyskach zbieranych latami - patrz Twoje 3 dodatkowe biblioteki, łącznie
150+ pozycji) są zauważalnie wolne, jeśli każdy wiersz to żywy widget
(CardWidget czy nawet lżejszy QWidget z PushButtonami - te ostatnie same
w sobie kosztują ~0.7ms/sztuka przy tworzeniu, więc 150 wierszy x 2
przyciski to już z runda 200ms+ tylko na przyciski, do tego dochodzą
etykiety, layouty itd.).

Rozwiązanie: prawdziwy QStyledItemDelegate, który MALUJE wiersz ręcznie
(QPainter) zamiast tworzyć dla niego żywe widgety Qt. Model danych to
zwykła lista Pythona, view (QListView) renderuje tylko to co widoczne w
oknie - klasyczna virtualizacja, tak jak w każdej porządnej liście z
tysiącami elementów. Kliknięcia w "przyciski" obsługiwane są przez
przechwycenie pozycji myszy względem narysowanych prostokątów, nie przez
prawdziwe QPushButton.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QTimer,
    QThread,
    QSize,
    QRect,
    QModelIndex,
    QAbstractListModel,
    QEvent,
)
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
)

from qfluentwidgets import (
    SearchLineEdit,
    FluentIcon,
    TitleLabel,
    TransparentToolButton,
    SwitchButton,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
    isDarkTheme,
)

from steamtools.core.library import scan_installed_games, InstalledGame
from steamtools.core.badges import (
    fetch_badge_progress,
    SteamCommunityError,
    BadgeProgress,
    format_cards_count,
    get_cached_badge_progress,
    set_cached_badge_progress,
)
from steamtools.core.config import load_community_session

_ROW_HEIGHT = 64
_BTN_WIDTH = 130
_BTN_HEIGHT = 32
_BTN_GAP = 8
_BTN_ACHIEVEMENTS = "achievements"
_BTN_IDLE = "idle"

_GameIdRole = Qt.ItemDataRole.UserRole + 1
_CardsRemainingRole = Qt.ItemDataRole.UserRole + 2


class GameListModel(QAbstractListModel):
    """Prosty model trzymający listę InstalledGame - żadnej logiki poza
    ekspozycją danych, cały ciężar renderowania jest w delegate.

    Dodatkowo trzyma mapę app_id -> liczba pozostałych kart (None = nie
    sprawdzano), żeby delegate mógł zablokować przycisk "Farmuj karty" dla
    gier bez dropów - to jest realizacja wymogu "nie pozwalaj farmić gier
    bez kart do zdobycia"."""

    def __init__(self, games: list[InstalledGame] | None = None, parent=None):
        super().__init__(parent)
        self._games: list[InstalledGame] = games or []
        self._cards_remaining: dict[int, int] = {}
        self._cards_checked: bool = False

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt API)
        return len(self._games)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        game = self._games[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return game.name
        if role == _GameIdRole:
            return game
        if role == _CardsRemainingRole:
            if not self._cards_checked:
                return None
            return self._cards_remaining.get(game.app_id, 0)
        return None

    def set_games(self, games: list[InstalledGame]) -> None:
        self.beginResetModel()
        self._games = games
        self.endResetModel()

    def set_cards_remaining(self, mapping: dict[int, int]) -> None:
        """Aktualizuje wiedzę o pozostałych kartach dla WSZYSTKICH gier w
        modelu naraz (po zescrapowaniu strony Badges). Gry nieobecne w
        `mapping` dostają 0 - strona Badges pokazuje tylko gry z
        niewyzerowanymi dropami, więc brak wpisu = brak kart."""
        self._cards_remaining = dict(mapping)
        self._cards_checked = True
        if self._games:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._games) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [_CardsRemainingRole])

    def has_card_data(self) -> bool:
        """True jeśli wynik scrapowania Badges został już choć raz
        wczytany do modelu - odróżnia to "sprawdzono, 0 gier ma karty" (dict
        pusty, ale sprawdzone) od "jeszcze nie sprawdzano" (dict pusty,
        bo brak danych)."""
        return self._cards_checked

    def game_at(self, row: int) -> InstalledGame | None:
        if 0 <= row < len(self._games):
            return self._games[row]
        return None


class GameRowDelegate(QStyledItemDelegate):
    """Ręcznie maluje wiersz gry: ikonę, tytuł, AppID i dwa "przyciski"
    (Osiągnięcia / Farmuj karty). Zero żywych widgetów per wiersz - to jest
    klucz do wydajności przy dużych bibliotekach."""

    achievementsClicked = pyqtSignal(int, str)
    idleClicked = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered_row: int = -1
        self._hovered_button: str | None = None

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, _ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        game: InstalledGame = index.data(_GameIdRole)
        if game is None:
            return
        cards_remaining = index.data(_CardsRemainingRole)  # None = nie sprawdzano, int = sprawdzono

        painter.save()
        rect = option.rect
        dark = isDarkTheme()

        # Tło wiersza (hover/selected)
        if option.state & QStyle.StateFlag.State_Selected:
            bg = QColor(255, 255, 255, 18) if dark else QColor(0, 0, 0, 12)
            painter.fillRect(rect, bg)
        elif index.row() == self._hovered_row:
            bg = QColor(255, 255, 255, 10) if dark else QColor(0, 0, 0, 6)
            painter.fillRect(rect, bg)

        text_color = QColor(230, 230, 230) if dark else QColor(30, 30, 30)
        subtitle_color = QColor(180, 180, 180) if dark else QColor(96, 96, 96)

        left_x = rect.left() + 16
        buttons_rect = self._buttons_rect(rect)
        text_right = buttons_rect.left() - 12

        # Tytuł
        title_font = QFont(painter.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(text_color)
        title_rect = QRect(left_x, rect.top() + 8, text_right - left_x, 20)
        metrics = QFontMetrics(title_font)
        elided = metrics.elidedText(game.name, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, elided)

        # Podtytuł (AppID + liczba pozostałych kart, jeśli już sprawdzono)
        subtitle_font = QFont(painter.font())
        subtitle_font.setWeight(QFont.Weight.Normal)
        subtitle_font.setPointSize(max(subtitle_font.pointSize() - 1, 7))
        painter.setFont(subtitle_font)
        painter.setPen(subtitle_color)
        subtitle_rect = QRect(left_x, rect.top() + 30, text_right - left_x, 16)
        subtitle_text = f"AppID {game.app_id}"
        if cards_remaining is not None:
            subtitle_text += f" - {format_cards_count(cards_remaining)}"
        painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignVCenter, subtitle_text)

        # Przycisk Osiągnięcia - zawsze aktywny, niezależnie od kart (user
        # może chcieć zobaczyć/edytować osiągnięcia gry bez dropów).
        self._paint_button(
            painter, self._achievements_rect(rect), "Osiągnięcia",
            hovered=(index.row() == self._hovered_row and self._hovered_button == _BTN_ACHIEVEMENTS),
            dark=dark, disabled=False,
        )

        # Przycisk Farmuj karty - wyszarzony i niereagujący na klik, gdy
        # WIADOMO że gra nie ma kart do zdobycia (cards_remaining == 0).
        # Gdy jeszcze nie sprawdzano (None), przycisk jest aktywny - nie
        # blokujemy na wyrost bez faktycznej wiedzy.
        idle_disabled = cards_remaining == 0
        self._paint_button(
            painter, self._idle_rect(rect),
            "Farmuj karty" if not idle_disabled else "Brak kart",
            hovered=(index.row() == self._hovered_row and self._hovered_button == _BTN_IDLE and not idle_disabled),
            dark=dark, disabled=idle_disabled,
        )

        painter.restore()

    def _paint_button(self, painter: QPainter, rect: QRect, text: str, hovered: bool, dark: bool, disabled: bool = False) -> None:
        if disabled:
            base = QColor(255, 255, 255, 6) if dark else QColor(0, 0, 0, 4)
        else:
            base = QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 8)
            if hovered:
                base = QColor(255, 255, 255, 35) if dark else QColor(0, 0, 0, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(rect, 6, 6)

        if disabled:
            text_color = QColor(120, 120, 120) if dark else QColor(180, 180, 180)
        else:
            text_color = QColor(230, 230, 230) if dark else QColor(40, 40, 40)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _buttons_rect(self, row_rect: QRect) -> QRect:
        total_width = _BTN_WIDTH * 2 + _BTN_GAP
        left = row_rect.right() - 16 - total_width
        top = row_rect.top() + (row_rect.height() - _BTN_HEIGHT) // 2
        return QRect(left, top, total_width, _BTN_HEIGHT)

    def _achievements_rect(self, row_rect: QRect) -> QRect:
        buttons = self._buttons_rect(row_rect)
        return QRect(buttons.left(), buttons.top(), _BTN_WIDTH, _BTN_HEIGHT)

    def _idle_rect(self, row_rect: QRect) -> QRect:
        buttons = self._buttons_rect(row_rect)
        return QRect(buttons.left() + _BTN_WIDTH + _BTN_GAP, buttons.top(), _BTN_WIDTH, _BTN_HEIGHT)

    def button_at(self, row_rect: QRect, pos) -> str | None:
        if self._achievements_rect(row_rect).contains(pos):
            return _BTN_ACHIEVEMENTS
        if self._idle_rect(row_rect).contains(pos):
            return _BTN_IDLE
        return None


class GameListView(QListView):
    """QListView z obsługą klikania w narysowane przez delegate przyciski
    oraz hover-highlight per przycisk (bez tego mysz najeżdżająca na wiersz
    nie dawałaby żadnej wizualnej informacji zwrotnej)."""

    achievementsRequested = pyqtSignal(int, str)
    idleRequested = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.delegate = GameRowDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(True)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        row = index.row() if index.isValid() else -1
        button = None
        if index.isValid():
            row_rect = self.visualRect(index)
            button = self.delegate.button_at(row_rect, event.pos())

        if row != self.delegate._hovered_row or button != self.delegate._hovered_button:
            self.delegate._hovered_row = row
            self.delegate._hovered_button = button
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self.delegate._hovered_row = -1
        self.delegate._hovered_button = None
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        if index.isValid():
            row_rect = self.visualRect(index)
            button = self.delegate.button_at(row_rect, event.pos())
            if button is not None:
                game = index.data(_GameIdRole)
                cards_remaining = index.data(_CardsRemainingRole)
                if game is not None:
                    if button == _BTN_ACHIEVEMENTS:
                        self.achievementsRequested.emit(game.app_id, game.name)
                    elif button == _BTN_IDLE:
                        # Blokada kliknięcia gdy WIADOMO (sprawdzono), że
                        # gra nie ma kart do zdobycia - to jest właściwa
                        # realizacja "nie pozwalaj farmić gier bez kart",
                        # nie tylko wizualna sugestia.
                        if cards_remaining == 0:
                            return
                        self.idleRequested.emit(game.app_id, game.name)
                return  # nie przekazuj dalej - to było kliknięcie w przycisk
        super().mousePressEvent(event)


class _FetchBadgeProgressThread(QThread):
    """Zapytanie HTTP do Steam Community w osobnym wątku - identyczny
    mechanizm jak w IdleView, celowo zduplikowany (nie wydzielony do
    wspólnej klasy) bo to prosty, kilkulinijkowy wrapper i dwie niezależne
    kopie są czytelniejsze niż dodatkowa warstwa abstrakcji dla tak małego
    fragmentu kodu."""

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


class LibraryView(QWidget):
    """Widok listy gier z paskiem wyszukiwania nad nią."""

    achievementsRequested = pyqtSignal(int, str)
    idleRequested = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryView")
        self._all_games: list[InstalledGame] = []
        self._cards_remaining_snapshot: dict[int, int] = {}
        self._badge_thread: Optional[_FetchBadgeProgressThread] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        header = TitleLabel("Biblioteka gier", self)
        root.addWidget(header)

        top_row = QHBoxLayout()
        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("Szukaj gry…")
        self.refresh_btn = TransparentToolButton(FluentIcon.SYNC, self)
        self.refresh_btn.setToolTip("Odśwież listę zainstalowanych gier (z dysku)")
        self.refresh_btn.clicked.connect(self.reload_games)
        top_row.addWidget(self.search, stretch=1)
        top_row.addWidget(self.refresh_btn)
        root.addLayout(top_row)

        filter_row = QHBoxLayout()
        self.check_cards_btn = TransparentToolButton(FluentIcon.SYNC, self)
        self.check_cards_btn.setToolTip(
            "Sprawdź, które gry mają jeszcze karty do zdobycia (pobiera dane "
            "ze Steam Community - wymaga sesji w Ustawieniach)"
        )
        self.check_cards_btn.clicked.connect(self._check_cards_remaining)
        filter_row.addWidget(self.check_cards_btn)
        filter_row.addWidget(CaptionLabel("Sprawdź pozostałe karty", self))

        self.only_with_cards_switch = SwitchButton(self)
        self.only_with_cards_switch.setOnText("Tak")
        self.only_with_cards_switch.setOffText("Nie")
        self.only_with_cards_switch.checkedChanged.connect(self._apply_filter)
        filter_row.addWidget(CaptionLabel("Pokaż tylko gry z kartami do zdobycia:", self))
        filter_row.addWidget(self.only_with_cards_switch)
        filter_row.addStretch(1)
        root.addLayout(filter_row)

        self.badge_progress_bar = IndeterminateProgressBar(self)
        self.badge_progress_bar.setVisible(False)
        root.addWidget(self.badge_progress_bar)

        self.model = GameListModel()
        self.list_view = GameListView(self)
        self.list_view.setModel(self.model)
        self.list_view.achievementsRequested.connect(self.achievementsRequested)
        self.list_view.idleRequested.connect(self.idleRequested)
        root.addWidget(self.list_view, stretch=1)

        # Debounce wyszukiwania - filtrowanie setek elementów przy KAŻDYM
        # naciśniętym znaku byłoby zbędnym obciążeniem.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _: self._filter_timer.start())

        # Wczytujemy wynik ewentualnego sprawdzenia kart wykonanego z INNEGO
        # widoku (np. Farm kart) w tej samej sesji aplikacji - bez tego ten
        # widok pokazywałby "Brak danych o kartach" mimo że sprawdzenie
        # faktycznie się odbyło, tylko zainicjowane gdzie indziej.
        cached = get_cached_badge_progress()
        if cached is not None:
            self._cards_remaining_snapshot = {r.app_id: r.cards_remaining for r in cached}
            self.model.set_cards_remaining(self._cards_remaining_snapshot)

        # Pierwsze ładowanie odłożone na następny cykl event loopa - budowanie
        # od razu w __init__ (zanim FluentWindow zdąży w pełni ułożyć
        # layout/stacked widget) bywało źródłem rozjechanego renderowania
        # przy pierwszym uruchomieniu na niektórych kompozytorach Wayland
        # (KDE Plasma) - widget łapał się w trakcie relayoutu.
        QTimer.singleShot(0, self.reload_games)

    def reload_games(self) -> None:
        self._all_games = scan_installed_games()

        if not self._all_games:
            InfoBar.warning(
                title="Brak gier",
                content="Nie znaleziono zainstalowanych gier Steam na tym koncie/dysku.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )

        # Model dostaje najpierw kartę pozostałych kart z poprzedniego
        # sprawdzenia (jeśli było), potem stosujemy filtr - inaczej świeżo
        # przeładowana lista straciłaby wiedzę o kartach do czasu kolejnego
        # ręcznego sprawdzenia. Robimy to TYLKO jeśli już kiedyś sprawdzano
        # karty w tej sesji - w przeciwnym razie set_games (wołane niżej w
        # _apply_filter -> set_games) i tak zresetuje stan modelu, a
        # przedwczesne set_cards_remaining({}) ustawiłoby błędnie "sprawdzono,
        # 0 gier ma karty" zamiast poprawnego "jeszcze nie sprawdzano".
        if self.model.has_card_data():
            self.model.set_cards_remaining(self._cards_remaining_snapshot)
        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        text = self.search.text().lower().strip()
        only_with_cards = self.only_with_cards_switch.isChecked()

        filtered = self._all_games
        if text:
            filtered = [
                g for g in filtered
                if text in g.name.lower() or text in str(g.app_id)
            ]
        if only_with_cards:
            if not self.model.has_card_data():
                # Zamiast błędu każącego userowi ręcznie kliknąć osobny
                # przycisk sprawdzania kart, po prostu sami je sprawdzamy -
                # włączenie przełącznika "Pokaż tylko gry z kartami" jest
                # samo w sobie wystarczająco jasną intencją, żeby zrobić to
                # automatycznie. _on_badge_progress_ok wywoła _apply_filter
                # ponownie po zakończeniu, więc filtr i tak w końcu się
                # zastosuje - tu tylko pokazujemy pustą listę tymczasowo,
                # w trakcie sprawdzania (progress bar informuje że coś się
                # dzieje).
                self._check_cards_remaining()
                filtered = []
            else:
                known_with_cards = {
                    app_id for app_id, count in self._cards_remaining_snapshot.items()
                    if count > 0
                }
                filtered = [g for g in filtered if g.app_id in known_with_cards]

        self.model.set_games(filtered)

    def _check_cards_remaining(self) -> None:
        session = load_community_session()
        if not session.is_configured():
            InfoBar.warning(
                title="Brak konfiguracji Steam Community",
                content="Skonfiguruj SteamID64 i ciasteczko sesji w "
                "Ustawieniach, żeby sprawdzać liczbę pozostałych kart.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            # Bez sesji nie da się w ogóle sprawdzić kart - cofamy
            # przełącznik "tylko z kartami", żeby nie zostawał włączony z
            # pustą, niewyjaśnioną listą (to jedyny scenariusz, w którym
            # user faktycznie musi coś zrobić ręcznie, w przeciwieństwie do
            # zwykłego "jeszcze nie sprawdzano", które teraz obsługujemy
            # automatycznie).
            if self.only_with_cards_switch.isChecked():
                self.only_with_cards_switch.setChecked(False)
            return

        if self._badge_thread is not None and self._badge_thread.isRunning():
            return  # zapytanie już w toku

        self.check_cards_btn.setEnabled(False)
        self.badge_progress_bar.setVisible(True)

        self._badge_thread = _FetchBadgeProgressThread(
            session.session_cookie, session.session_id, self
        )
        self._badge_thread.finished_ok.connect(self._on_badge_progress_ok)
        self._badge_thread.finished_error.connect(self._on_badge_progress_error)
        self._badge_thread.start()

    def _on_badge_progress_ok(self, results: list) -> None:
        self.check_cards_btn.setEnabled(True)
        self.badge_progress_bar.setVisible(False)

        set_cached_badge_progress(results)

        mapping = {r.app_id: r.cards_remaining for r in results}
        self._cards_remaining_snapshot = mapping
        self.model.set_cards_remaining(mapping)

        InfoBar.success(
            title="Sprawdzono",
            content=f"Znaleziono {len(results)} gier z kartami do zdobycia.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3500,
        )

        # Jeśli filtr "tylko z kartami" był (nieudanie) włączony wcześniej
        # bez danych, teraz mamy dane - odśwież widok żeby faktycznie
        # zadziałał bez konieczności przełączania go ponownie ręcznie.
        if self.only_with_cards_switch.isChecked():
            self._apply_filter()

    def _on_badge_progress_error(self, message: str) -> None:
        self.check_cards_btn.setEnabled(True)
        self.badge_progress_bar.setVisible(False)
        InfoBar.error(
            title="Błąd Steam Community",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=6000,
        )
        # Sprawdzanie się nie udało, więc nie ma czym filtrować - cofamy
        # przełącznik zamiast zostawiać go włączonym z pustą, milczącą
        # listą (błąd powyżej i tak już wyjaśnia co poszło nie tak).
        if self.only_with_cards_switch.isChecked():
            self.only_with_cards_switch.setChecked(False)
