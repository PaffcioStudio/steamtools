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
    verify_session,
    SessionInfo,
    SteamCommunityError,
    SteamSessionExpiredError,
)
from steamtools.core.config import (
    CommunitySession,
    save_community_session,
    load_community_session,
    clear_community_session,
)


class _ValidateSessionThread(QThread):
    """Weryfikacja sesji w osobnym wątku (UI nie blokuje się na czas
    requestu). Trzy możliwe wyniki, celowo rozdzielone:
      verified   - Steam potwierdził zalogowanie (dostajemy SessionInfo),
      expired    - Steam potwierdził, że ciasteczko NIE loguje,
      unverified - nie dało się ocenić (brak sieci, throttling, ...) -
                   to NIE jest dowód, że sesja wygasła.
    """

    verified = pyqtSignal(object)  # SessionInfo
    expired = pyqtSignal(str)
    unverified = pyqtSignal(str)

    def __init__(self, session_cookie: str, session_id: str, parent=None):
        super().__init__(parent)
        self.session_cookie = session_cookie
        self.session_id = session_id

    def run(self) -> None:
        try:
            info = verify_session(self.session_cookie, self.session_id)
        except SteamSessionExpiredError as exc:
            self.expired.emit(str(exc))
        except SteamCommunityError as exc:
            self.unverified.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - wątek nie może rzucić na zewnątrz
            self.unverified.emit(f"Nieoczekiwany błąd: {exc}")
        else:
            self.verified.emit(info)


class AccountView(QWidget):
    # Emitowane przy weryfikacji ZAPISANEJ sesji w tle (start programu).
    # Zakładka Konto jest wtedy zwykle niewidoczna, więc InfoBar z tego
    # widoku nigdy nie trafiłby do usera - komunikat pokazuje MainWindow.
    sessionExpired = pyqtSignal(str)
    sessionVerified = pyqtSignal(object)  # SessionInfo

    _MODE_SAVE = "save"        # klik "Zapisz": zapisz dopiero po weryfikacji
    _MODE_CHECK = "check"      # klik "Sprawdź sesję": tylko sprawdź
    _MODE_STARTUP = "startup"  # tło przy starcie: tylko sprawdź zapisane

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
        self.check_session_btn = PushButton("Sprawdź sesję", card, FluentIcon.SYNC)
        self.clear_session_btn = PushButton("Wyczyść", card, FluentIcon.DELETE)
        self.save_session_btn.clicked.connect(self._save_community_session)
        self.check_session_btn.clicked.connect(self._check_session_clicked)
        self.clear_session_btn.clicked.connect(self._clear_community_session)
        buttons_row.addWidget(self.save_session_btn)
        buttons_row.addWidget(self.check_session_btn)
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

        # Stały status sesji - wynik OSTATNIEJ prawdziwej weryfikacji u Steam
        # (nie samego formatu ciasteczka, który pokazuje wiersz wyżej).
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_icon = IconWidget(FluentIcon.INFO, card)
        self.status_icon.setFixedSize(16, 16)
        status_row.addWidget(self.status_icon)
        self.status_label = BodyLabel("", card)
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, stretch=1)
        layout.addLayout(status_row)
        self._set_status(
            "unknown",
            "Sesja nie była jeszcze sprawdzona." if saved.session_cookie
            else "Brak zapisanej sesji.",
        )

        self._validate_thread: _ValidateSessionThread | None = None
        self._pending_mode: str = self._MODE_CHECK
        self._pending_cookie: str = ""
        self._pending_session_id: str = ""

        wrapper_layout.addWidget(card)

        return wrapper

    def _set_status(self, kind: str, text: str) -> None:
        icon, color = {
            "valid": (FluentIcon.ACCEPT, "#2ecc71"),
            "expired": (FluentIcon.CLOSE, "#e74c3c"),
            "unknown": (FluentIcon.INFO, "#95a5a6"),
        }[kind]
        self.status_icon.setIcon(icon)
        self.status_label.setText(text)
        self.status_label.setTextColor(color, color)

    def verify_saved_session(self) -> None:
        """Wołane przez MainWindow raz po starcie: jeśli jest zapisane
        steamLoginSecure, od razu sprawdza u Steam, czy wciąż loguje -
        user dowiaduje się o wygaśnięciu na wejściu, a nie dopiero gdy
        "Sprawdź i farm wszystkie" zwróci nic."""
        saved = load_community_session()
        if not saved.is_configured():
            return
        self._start_verification(
            saved.session_cookie, saved.session_id, self._MODE_STARTUP
        )

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

        # Poprawny FORMAT nie znaczy, że token loguje - zapisujemy dopiero
        # po tym, jak Steam potwierdzi zalogowanie (patrz _on_verified).
        self._start_verification(cookie, session_id, self._MODE_SAVE)

    def _check_session_clicked(self) -> None:
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
        self._start_verification(cookie, session_id, self._MODE_CHECK)

    def _start_verification(self, cookie: str, session_id: str, mode: str) -> None:
        # Poprzednia weryfikacja jeszcze trwa - nie startujemy drugiej
        # równolegle (przyciski są wtedy i tak zablokowane; to zabezpieczenie
        # dotyczy głównie startu w tle zbiegającego się z kliknięciem).
        if self._validate_thread is not None and self._validate_thread.isRunning():
            return

        self._pending_mode = mode
        self._pending_cookie = cookie
        self._pending_session_id = session_id

        self.session_check_bar.setVisible(True)
        self.save_session_btn.setEnabled(False)
        self.check_session_btn.setEnabled(False)
        self._set_status("unknown", "Sprawdzanie sesji u Steam...")

        self._validate_thread = _ValidateSessionThread(cookie, session_id, self)
        self._validate_thread.verified.connect(self._on_verified)
        self._validate_thread.expired.connect(self._on_expired)
        self._validate_thread.unverified.connect(self._on_unverified)
        self._validate_thread.start()

    def _finish_verification_ui(self) -> None:
        self.session_check_bar.setVisible(False)
        self.save_session_btn.setEnabled(True)
        self.check_session_btn.setEnabled(True)

    def _on_verified(self, info: SessionInfo) -> None:
        self._finish_verification_ui()

        who = info.persona_name or "nieznana nazwa"
        self._set_status(
            "valid",
            f"Sesja ważna - zalogowano jako {who} (SteamID64: {info.steam_id64}).",
        )

        if self._pending_mode == self._MODE_SAVE:
            save_community_session(
                CommunitySession(
                    session_cookie=self._pending_cookie,
                    session_id=self._pending_session_id,
                )
            )
            InfoBar.success(
                title="Zapisano",
                content=f"Zalogowano jako {who}. Dane sesji zostały zapisane.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000,
            )
        elif self._pending_mode == self._MODE_CHECK:
            InfoBar.success(
                title="Sesja ważna",
                content=f"Steam rozpoznaje to ciasteczko - konto: {who}.",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )
        self.sessionVerified.emit(info)

    def _on_expired(self, error: str) -> None:
        self._finish_verification_ui()
        self._set_status(
            "expired",
            "Sesja wygasła lub jest nieprawidłowa - zaloguj się ponownie na "
            "steamcommunity.com i wklej świeże ciasteczko steamLoginSecure.",
        )

        # Pól NIE czyścimy: gdyby Steam kiedyś zmienił stronę i weryfikacja
        # dała fałszywy alarm, user nie straciłby ważnego ciasteczka. Martwy
        # token i tak nadpisuje się jednym wklejeniem.
        if self._pending_mode == self._MODE_STARTUP:
            self.sessionExpired.emit(error)
            return

        title = (
            "Nie zapisano - sesja nieważna"
            if self._pending_mode == self._MODE_SAVE
            else "Sesja Steam wygasła"
        )
        InfoBar.error(
            title=title,
            content=f"{error} Zaloguj się ponownie i wklej nowe ciasteczko.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=8000,
        )

    def _on_unverified(self, error: str) -> None:
        self._finish_verification_ui()
        self._set_status("unknown", f"Nie udało się sprawdzić sesji: {error}")

        if self._pending_mode == self._MODE_STARTUP:
            return  # cicho - to nie jest dowód problemu z sesją

        if self._pending_mode == self._MODE_SAVE:
            # Brak sieci nie powinien blokować zapisu - format jest poprawny.
            save_community_session(
                CommunitySession(
                    session_cookie=self._pending_cookie,
                    session_id=self._pending_session_id,
                )
            )
            InfoBar.warning(
                title="Zapisano, ale nie zweryfikowano",
                content=f"Nie udało się sprawdzić sesji u Steam: {error}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        else:
            InfoBar.warning(
                title="Nie udało się sprawdzić sesji",
                content=error,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )

    def _clear_community_session(self) -> None:
        clear_community_session()
        self.session_cookie_input.clear()
        self.session_id_input.clear()
        self._set_status("unknown", "Brak zapisanej sesji.")
        InfoBar.info(
            title="Wyczyszczono",
            content="Dane sesji Steam Community zostały usunięte.",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
