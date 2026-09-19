"""Widok "Konto" - konfiguracja i walidacja sesji Steam Community
(steamLoginSecure/sessionid), używanej przez core/badges.py do scrapowania
strony Badges (liczba pozostałych kart do zdobycia per gra).

Wydzielone z SettingsView do własnej, widocznej zakładki w sidebarze
(między "Informacje" a "Ustawienia") - schowanie tej sekcji na dole
Ustawień sprawiało, że nowi userzy nie odkrywali jej wcale i mogli
odnieść wrażenie, że farmienie kart z licznikiem pozostałych dropów po
prostu nie działa / nie istnieje w programie."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    StrongBodyLabel,
    CardWidget,
    ScrollArea,
    PrimaryPushButton,
    PushButton,
    LineEdit,
    PasswordLineEdit,
    IconWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
)

from steamtools.core.badges import (
    extract_steam_id64_from_cookie,
    fetch_badge_progress,
    SteamCommunityError,
)
from steamtools.core.config import (
    CommunitySession,
    save_community_session,
    load_community_session,
    clear_community_session,
)


class _ValidateSessionThread(QThread):
    """Próba pobrania strony Badges w osobnym wątku, żeby sprawdzić czy
    zapisane steamLoginSecure faktycznie jeszcze loguje - bez blokowania
    UI na czas requestu. Sukces (nawet pusta lista odznak) = sesja ważna;
    SteamCommunityError = sesja wygasła/błędna (Steam zwrócił stronę
    logowania zamiast Badges)."""

    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def __init__(self, session_cookie: str, session_id: str, parent=None):
        super().__init__(parent)
        self.session_cookie = session_cookie
        self.session_id = session_id

    def run(self) -> None:
        try:
            fetch_badge_progress(self.session_cookie, self.session_id)
            self.finished_ok.emit()
        except SteamCommunityError as exc:
            self.finished_error.emit(str(exc))


class AccountView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountView")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.frameShape().NoFrame)

        content = QWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel("Konto", content))
        root.addWidget(
            self._build_community_session_group(content)
        )
        root.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _build_community_session_group(self, parent: QWidget) -> QWidget:
        wrapper = QWidget(parent)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.addWidget(
            SubtitleLabel("Steam Community (liczba pozostałych kart)", wrapper)
        )
        header_row.addStretch(1)
        wrapper_layout.addLayout(header_row)

        # Karta z realnym marginesem wewnętrznym i tłem, spójna wizualnie z
        # SettingCardGroup w Ustawieniach.
        card = CardWidget(wrapper)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        info_row = QHBoxLayout()
        info_icon = IconWidget(FluentIcon.INFO, card)
        info_icon.setFixedSize(16, 16)
        info_row.addWidget(info_icon, alignment=Qt.AlignmentFlag.AlignTop)
        info = BodyLabel(
            "Aby zobaczyć ile kart zostało do zdobycia w danej grze (zakładka "
            "Farm kart), SteamTools musi zescrapować Twoją prywatną stronę "
            "Badges - Steamworks API nie udostępnia tej informacji.",
            card,
        )
        info.setWordWrap(True)
        info_row.addWidget(info, stretch=1)
        layout.addLayout(info_row)

        howto_card = CardWidget(card)
        howto_card.setBorderRadius(6)
        howto_layout = QVBoxLayout(howto_card)
        howto_layout.setContentsMargins(12, 10, 12, 10)
        howto_layout.setSpacing(4)
        howto_title = StrongBodyLabel("Jak zdobyć ciasteczko sesji:", howto_card)
        howto_layout.addWidget(howto_title)
        howto_steps = CaptionLabel(
            "1. Zaloguj się na steamcommunity.com w przeglądarce\n"
            "2. Otwórz narzędzia deweloperskie (F12)\n"
            "3. Zakładka Application/Storage -> Cookies -> steamcommunity.com\n"
            "4. Skopiuj wartość ciasteczka \"steamLoginSecure\" (sessionid "
            "jest opcjonalne i zwykle niepotrzebne)",
            howto_card,
        )
        howto_steps.setWordWrap(True)
        howto_steps.setTextColor("#606060", "#c0c0c0")
        howto_layout.addWidget(howto_steps)
        layout.addWidget(howto_card)

        saved = load_community_session()

        session_id_label = StrongBodyLabel("Ciasteczko sessionid (opcjonalne)", card)
        layout.addWidget(session_id_label)

        self.session_id_input = LineEdit(card)
        self.session_id_input.setPlaceholderText(
            "np. 6c5019dfb3709248f09d92ea (token CSRF, 24 znaki hex) - "
            "zwykle niepotrzebne, samo steamLoginSecure wystarcza"
        )
        self.session_id_input.setText(saved.session_id)
        layout.addWidget(self.session_id_input)

        cookie_label = StrongBodyLabel("Ciasteczko steamLoginSecure (wymagane)", card)
        layout.addWidget(cookie_label)

        self.session_cookie_input = PasswordLineEdit(card)
        self.session_cookie_input.setPlaceholderText(
            "np. 76561198012345678%7C%7CA1B2C3D4E5F6..."
        )
        self.session_cookie_input.setText(saved.session_cookie)
        self.session_cookie_input.textChanged.connect(self._update_detected_steam_id)
        layout.addWidget(self.session_cookie_input)

        # Podpowiedź pokazująca na żywo wykryte SteamID64 - potwierdza
        # userowi, że wklejona wartość jest poprawna, zanim jeszcze kliknie
        # Zapisz. SteamID64 jest wyliczane automatycznie z tego ciasteczka
        # (patrz core/badges.py: extract_steam_id64_from_cookie) - user
        # NIE musi go nigdzie osobno podawać ani szukać. Ikona zamiast
        # emotikonu tekstowego - spójniej z resztą UI (żadny inny komunikat
        # w aplikacji nie używa emoji, tylko IconWidget z FluentIcon).
        detected_row = QHBoxLayout()
        detected_row.setSpacing(6)
        self.detected_id_icon = IconWidget(FluentIcon.ACCEPT, card)
        self.detected_id_icon.setFixedSize(14, 14)
        self.detected_id_icon.setVisible(False)
        detected_row.addWidget(self.detected_id_icon)
        self.detected_id_label = CaptionLabel("", card)
        detected_row.addWidget(self.detected_id_label, stretch=1)
        layout.addLayout(detected_row)
        self._update_detected_steam_id()

        buttons_row = QHBoxLayout()
        self.save_session_btn = PrimaryPushButton("Zapisz", card, FluentIcon.SAVE)
        self.clear_session_btn = PushButton("Wyczyść", card, FluentIcon.DELETE)
        self.save_session_btn.clicked.connect(self._save_community_session)
        self.clear_session_btn.clicked.connect(self._clear_community_session)
        buttons_row.addWidget(self.save_session_btn)
        buttons_row.addWidget(self.clear_session_btn)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        # Pasek postępu na czas sprawdzania sesji w tle (nieokreślony,
        # bo request do Steam Community nie ma mierzalnego progresu) -
        # domyślnie schowany, pokazywany tylko na czas walidacji.
        self.session_check_bar = IndeterminateProgressBar(card)
        self.session_check_bar.setFixedHeight(3)
        self.session_check_bar.setVisible(False)
        layout.addWidget(self.session_check_bar)

        self._validate_thread: _ValidateSessionThread | None = None

        wrapper_layout.addWidget(card)

        # Jeśli sesja była już zapisana z poprzedniego uruchomienia programu,
        # sprawdź od razu przy otwarciu zakładki Konto czy steamLoginSecure
        # wciąż jest ważne - zamiast czekać, aż user sam zauważy błąd
        # dopiero przy próbie farmienia/sprawdzania osiągnięć.
        if saved.session_cookie:
            self._validate_session_in_background(saved.session_cookie, saved.session_id)

        return wrapper

    def _update_detected_steam_id(self, *_args) -> None:
        cookie = self.session_cookie_input.text().strip()
        if not cookie:
            self.detected_id_icon.setVisible(False)
            self.detected_id_label.setText("")
            return

        steam_id = extract_steam_id64_from_cookie(cookie)
        if steam_id:
            self.detected_id_icon.setVisible(True)
            self.detected_id_label.setText(f"Wykryto SteamID64: {steam_id}")
            self.detected_id_label.setTextColor("#2ecc71", "#2ecc71")
        else:
            self.detected_id_icon.setVisible(False)
            self.detected_id_label.setText(
                "Nie rozpoznano SteamID64 w tym ciasteczku - sprawdź, "
                "czy wartość jest skopiowana w całości."
            )
            self.detected_id_label.setTextColor("#e67e22", "#e67e22")

    def _save_community_session(self) -> None:
        cookie = self.session_cookie_input.text().strip()
        session_id = self.session_id_input.text().strip()

        if not cookie:
            InfoBar.warning(
                title="Brak ciasteczka",
                content="Wklej wartość ciasteczka steamLoginSecure.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            return

        if extract_steam_id64_from_cookie(cookie) is None:
            InfoBar.warning(
                title="Nieprawidłowe ciasteczko",
                content="Nie udało się rozpoznać SteamID64 w podanej wartości - "
                "sprawdź, czy ciasteczko steamLoginSecure zostało skopiowane "
                "w całości (format: <SteamID64>||<token>).",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            return

        save_community_session(
            CommunitySession(session_cookie=cookie, session_id=session_id)
        )
        InfoBar.success(
            title="Zapisano",
            content="Dane sesji Steam Community zostały zapisane.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )

        # Format ciasteczka jest OK (steam_id64 wykryty powyżej), ale to
        # nie znaczy że sam token wciąż loguje - sprawdzamy to naprawdę,
        # w tle, żeby nie blokować UI na czas requestu do Steam Community.
        self._validate_session_in_background(cookie, session_id)

    def _validate_session_in_background(self, cookie: str, session_id: str) -> None:
        # Gdyby poprzednia walidacja jeszcze trwała (np. user zdążył
        # kliknąć Zapisz drugi raz zanim pierwszy request wrócił) - nie
        # startujemy drugiego wątku równolegle, tylko czekamy aż poprzedni
        # się zakończy (Qt i tak by odrzucił start już uruchomionego QThread).
        if self._validate_thread is not None and self._validate_thread.isRunning():
            return

        self.session_check_bar.setVisible(True)
        self._validate_thread = _ValidateSessionThread(cookie, session_id, self)
        self._validate_thread.finished_ok.connect(self._on_session_valid)
        self._validate_thread.finished_error.connect(self._on_session_invalid)
        self._validate_thread.start()

    def _on_session_valid(self) -> None:
        self.session_check_bar.setVisible(False)

    def _on_session_invalid(self, error: str) -> None:
        self.session_check_bar.setVisible(False)

        # Zapisane dane już nie działają - czyścimy je od razu, żeby user
        # nie farmił/sprawdzał osiągnięć "na ślepo" z martwym tokenem i mógł
        # od razu wkleić nowe steamLoginSecure w puste pola.
        clear_community_session()
        self.session_cookie_input.clear()
        self.session_id_input.clear()
        self._update_detected_steam_id()

        InfoBar.error(
            title="Sesja Steam wygasła",
            content=(
                "Nie udało się zalogować przy użyciu zapisanego "
                "steamLoginSecure - Steam odrzucił token. Pola zostały "
                f"wyczyszczone, wklej nowe dane. ({error})"
            ),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=8000,
        )

    def _clear_community_session(self) -> None:
        clear_community_session()
        self.session_cookie_input.clear()
        self.session_id_input.clear()
        InfoBar.info(
            title="Wyczyszczono",
            content="Dane sesji Steam Community zostały usunięte.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
