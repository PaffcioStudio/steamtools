"""Widok "Informacje" - wersja aplikacji, autor, inspiracje, opis projektu,
FAQ i sprawdzanie aktualizacji."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    HyperlinkButton,
    FluentIcon,
    IconWidget,
    ScrollArea,
    ExpandGroupSettingCard,
    SettingCardGroup,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
)

__version__ = "0.1.0"

_REPO_URL = "https://github.com/PaffcioStudio/steamtools"
_ROADMAP_FILE = "ROADMAP.md"


class _CheckUpdateThread(QThread):
    """Sprawdza najnowszy tag/release w repo GitHub (jeśli projekt tam
    trafi). Na razie działa w trybie best-effort: jeśli nie ma dostępu do
    sieci albo repo jeszcze nie istnieje publicznie, po prostu informuje
    o tym zamiast się wywalać."""

    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        try:
            import urllib.request
            import json

            api_url = _REPO_URL.replace(
                "github.com", "api.github.com/repos"
            ) + "/releases/latest"
            req = urllib.request.Request(
                api_url, headers={"User-Agent": "SteamTools"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            if not latest:
                self.finished_error.emit("Nie udało się odczytać wersji z odpowiedzi.")
                return
            self.finished_ok.emit(latest)
        except Exception as exc:  # noqa: BLE001 - best-effort, pokazujemy dowolny błąd
            self.finished_error.emit(str(exc))


class AboutView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AboutView")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # --- Nagłówek ---
        header_card = CardWidget(content)
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(20, 20, 20, 20)

        icon = IconWidget(FluentIcon.GAME, header_card)
        icon.setFixedSize(48, 48)
        header_layout.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.addWidget(TitleLabel("SteamTools", header_card))
        title_col.addWidget(
            CaptionLabel(f"Wersja {__version__}", header_card)
        )
        header_layout.addLayout(title_col, stretch=1)

        self.update_btn = PrimaryPushButton(
            "Sprawdź aktualizacje", header_card, FluentIcon.SYNC
        )
        self.update_btn.clicked.connect(self._check_updates)
        header_layout.addWidget(self.update_btn)

        root.addWidget(header_card)

        self.update_progress = IndeterminateProgressBar(content)
        self.update_progress.setVisible(False)
        root.addWidget(self.update_progress)

        # --- Opis projektu ---
        root.addWidget(SubtitleLabel("O projekcie", content))
        desc = BodyLabel(
            "SteamTools to natywna, linuksowa aplikacja łącząca menedżer "
            "osiągnięć Steam oraz farmienie kart kolekcjonerskich (card "
            "idling) w jednym, nowoczesnym interfejsie. Powstała jako "
            "niezależna od Windows alternatywa dla dwóch klasycznych "
            "narzędzi community, które nigdy nie działały natywnie na "
            "Linuksie.",
            content,
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        # --- Inspiracje ---
        root.addWidget(SubtitleLabel("Inspiracje", content))
        insp = BodyLabel(
            "• Steam Achievement Manager (SAM) - menedżer osiągnięć "
            "napisany w C#/WinForms/.NET Framework, działający tylko na "
            "Windows (lub przez Wine).\n"
            "• idle_master_extended - narzędzie do farmienia kart "
            "kolekcjonerskich, również C#/WinForms, ten sam problem z "
            "przenośnością.\n\n"
            "SteamTools nie zawiera kodu z żadnego z tych projektów - "
            "to niezależna implementacja w Pythonie/PyQt6, komunikująca "
            "się ze Steamem przez natywne (Linux) Steamworks SDK.",
            content,
        )
        insp.setWordWrap(True)
        root.addWidget(insp)

        # --- FAQ ---
        root.addWidget(SubtitleLabel("FAQ", content))
        root.addWidget(self._build_faq_card(content))

        # --- Linki ---
        root.addWidget(SubtitleLabel("Linki", content))
        links_row = QHBoxLayout()
        links_row.addWidget(
            HyperlinkButton(_REPO_URL, "Repozytorium projektu", content)
        )
        links_row.addWidget(
            HyperlinkButton(
                "https://partner.steamgames.com/downloads/steamworks_sdk.zip",
                "Steamworks SDK",
                content,
            )
        )
        links_row.addStretch(1)
        root.addLayout(links_row)

        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._update_thread: _CheckUpdateThread | None = None

    def _build_faq_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        faq_items = [
            (
                "Dlaczego osiągnięcia/farm kart nie działają?",
                "Upewnij się, że klient Steam jest uruchomiony i zalogowany "
                "(status widoczny w zakładce Ustawienia i na pasku "
                "powiadomień) oraz że posiadasz daną grę na koncie.",
            ),
            (
                "Dlaczego brak libsteam_api.so?",
                "Plik pochodzi z oficjalnego Steamworks SDK Valve i ze "
                "względu na licencję nie zawsze jest dołączony automatycznie. "
                "Uruchom ./venv.sh - sprawdzi obecność pliku i w razie "
                "potrzeby wskaże link do pobrania.",
            ),
            (
                "Czy SteamTools może zbanować moje konto?",
                "Aplikacja korzysta wyłącznie z oficjalnego, publicznego "
                "Steamworks API (dokładnie tego samego, którego używają same "
                "gry do zapisu postępów) - nie modyfikuje pamięci procesów "
                "ani plików gry. Mimo to każda ingerencja w statystyki "
                "poza normalną rozgrywką niesie teoretyczne ryzyko po "
                "stronie Valve - używaj świadomie.",
            ),
            (
                "Ile gier mogę farmić jednocześnie?",
                "Praktyczny limit klienta Steam to około 32 gry na raz - "
                "tyle samo dotyczy tego narzędzia.",
            ),
        ]

        for question, answer in faq_items:
            q_row = QHBoxLayout()
            q_row.setSpacing(6)
            q_icon = IconWidget(FluentIcon.HELP, card)
            q_icon.setFixedSize(14, 14)
            q_row.addWidget(q_icon, alignment=Qt.AlignmentFlag.AlignTop)
            q_label = BodyLabel(question, card)
            q_label.setStyleSheet("font-weight: 600;")
            q_label.setWordWrap(True)
            q_row.addWidget(q_label, stretch=1)
            layout.addLayout(q_row)

            a_label = CaptionLabel(answer, card)
            a_label.setWordWrap(True)
            layout.addWidget(a_label)

        return card

    def _check_updates(self) -> None:
        self.update_btn.setEnabled(False)
        self.update_progress.setVisible(True)

        self._update_thread = _CheckUpdateThread(self)
        self._update_thread.finished_ok.connect(self._on_update_ok)
        self._update_thread.finished_error.connect(self._on_update_error)
        self._update_thread.start()

    def _on_update_ok(self, latest_version: str) -> None:
        self.update_progress.setVisible(False)
        self.update_btn.setEnabled(True)

        if latest_version != __version__:
            InfoBar.success(
                title="Dostępna aktualizacja",
                content=f"Nowa wersja: {latest_version} (masz {__version__}).",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        else:
            InfoBar.info(
                title="Aktualne",
                content=f"Masz najnowszą wersję ({__version__}).",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _on_update_error(self, message: str) -> None:
        self.update_progress.setVisible(False)
        self.update_btn.setEnabled(True)
        InfoBar.warning(
            title="Nie udało się sprawdzić aktualizacji",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )
