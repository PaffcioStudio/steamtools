"""Trwały pasek z komunikatem u góry okna (np. "Sesja Steam wygasła").

Dlaczego nie qfluentwidgets.InfoBar: InfoBar zawija tekst raz, w momencie
utworzenia, według szerokości rodzica, a przycisk dokładany przez
addWidget() nie jest do tej szerokości wliczany. Efekt: pasek bywa
szerszy od okna (tytuł obcięty po lewej, przycisk po prawej), a przy
zmianie rozmiaru okna tekst skaluje się dziwnie.

Ten widget działa inaczej: etykiety mają włączone zawijanie wierszy, a
wysokość paska jest wyliczana z aktualnej szerokości (heightForWidth),
więc tekst zawsze mieści się w oknie, a pasek rośnie w dół zamiast
wystawać na boki.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PushButton,
    StrongBodyLabel,
    TransparentToolButton,
    isDarkTheme,
)

_SIDE_MARGIN = 16
_TOP_MARGIN = 8


class MessageBanner(QFrame):
    """Pasek błędu z tytułem, zawijanym opisem, przyciskiem akcji i
    zamykaniem. Pozycjonowanie względem okna rodzica robi `reposition()`
    (wołane przez MainWindow przy pokazaniu i zmianie rozmiaru)."""

    actionClicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(
        self,
        title: str,
        content: str,
        action_text: str,
        parent: QWidget,
        top_offset=0,
    ):
        super().__init__(parent)
        self._top_offset = top_offset  # int albo funkcja zwracająca int

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 10, 8, 10)
        root.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = StrongBodyLabel(title, self)
        self.title_label.setWordWrap(True)
        self.content_label = BodyLabel(content, self)
        self.content_label.setWordWrap(True)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.content_label)
        root.addLayout(text_col, stretch=1)

        self.action_btn = PushButton(action_text, self)
        self.action_btn.clicked.connect(self.actionClicked)
        root.addWidget(self.action_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.close_btn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.clicked.connect(self.dismiss)
        root.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def dismiss(self) -> None:
        self.hide()
        self.closed.emit()

    def reposition(self) -> None:
        """Dopasowuje szerokość do okna rodzica (z marginesami po bokach),
        a wysokość do tego, ile miejsca zajmie zawinięty tekst."""
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(parent.width() - 2 * _SIDE_MARGIN, 200)
        layout = self.layout()
        height = layout.heightForWidth(width) if layout.hasHeightForWidth() else -1
        if height <= 0:
            height = layout.sizeHint().height()
        self.setFixedSize(width, height)
        offset = self._top_offset() if callable(self._top_offset) else self._top_offset
        self.move(_SIDE_MARGIN, offset + _TOP_MARGIN)
        self.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        # Kolory jak w InfoBar.error, ale rysowane przy każdym repaincie,
        # więc od razu reagują na zmianę motywu jasny/ciemny.
        dark = isDarkTheme()
        bg = QColor(68, 39, 38) if dark else QColor(253, 231, 233)
        border = QColor(0, 0, 0, 40) if not dark else QColor(0, 0, 0, 60)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
