"""Widok "Ustawienia" - motyw, informacje o Steamworks SDK, o aplikacji."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    StrongBodyLabel,
    CardWidget,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
    OptionsSettingCard,
    PushSettingCard,
    PrimaryPushButton,
    PushButton,
    LineEdit,
    PasswordLineEdit,
    IconWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    setTheme,
    Theme,
    qconfig,
    OptionsConfigItem,
    OptionsValidator,
    ConfigItem,
    BoolValidator,
    QConfig,
)

from steamtools.core.steamworks import is_steam_running
from steamtools.core.badges import extract_steam_id64_from_cookie
from steamtools.core.config import (
    CommunitySession,
    save_community_session,
    load_community_session,
    clear_community_session,
)


class AppConfig(QConfig):
    dark_mode = OptionsConfigItem(
        "Appearance", "DarkMode", "Auto", OptionsValidator(["Light", "Dark", "Auto"])
    )
    auto_store = ConfigItem("Achievements", "AutoStore", False, BoolValidator())
    # Domyślnie włączone - zamknięcie okna (X) chowa aplikację do tray zamiast
    # ją kończyć, żeby farmienie kart / idle w tle nie ucinało się przez
    # przypadkowe kliknięcie w X. Pełne zakończenie programu jest zawsze
    # dostępne z menu kontekstowego ikonki w tray.
    minimize_to_tray = ConfigItem("Behavior", "MinimizeToTray", True, BoolValidator())


config = AppConfig()


class SettingsView(QWidget):
    openAboutRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsView")

        # Cała zawartość Ustawień osadzona w ScrollArea - lista ustawień
        # będzie tylko rosła (kolejne etapy ROADMAP dokładają sekcje), więc
        # bez przewijania treść zaczęłaby się wychodzić poza widoczny obszar
        # okna na mniejszych rozdzielczościach zamiast skalować się przez scroll.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.frameShape().NoFrame)

        content = QWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(TitleLabel("Ustawienia", content))

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        steam_running = is_steam_running()
        status_icon = IconWidget(
            FluentIcon.ACCEPT if steam_running else FluentIcon.CANCEL, content
        )
        status_icon.setFixedSize(14, 14)
        status_row.addWidget(status_icon)
        status_text = (
            "Klient Steam: uruchomiony"
            if steam_running
            else "Klient Steam: NIE wykryto (wymagany do osiągnięć i farmienia kart)"
        )
        status_label = CaptionLabel(status_text, content)
        if not steam_running:
            status_label.setTextColor("#e67e22", "#e67e22")
        status_row.addWidget(status_label, stretch=1)
        root.addLayout(status_row)

        appearance_group = SettingCardGroup("Wygląd", content)
        self.theme_card = OptionsSettingCard(
            config.dark_mode,
            FluentIcon.BRUSH,
            "Motyw",
            "Jasny / Ciemny / Zgodny z systemem",
            texts=["Jasny", "Ciemny", "Systemowy"],
            parent=appearance_group,
        )
        appearance_group.addSettingCard(self.theme_card)
        root.addWidget(appearance_group)

        behavior_group = SettingCardGroup("Zachowanie", content)
        self.autostore_card = SwitchSettingCard(
            FluentIcon.SAVE,
            "Automatyczny zapis osiągnięć",
            "Zapisuj zmiany od razu po zaznaczeniu, bez przycisku 'Zapisz zmiany'",
            config.auto_store,
            parent=behavior_group,
        )
        behavior_group.addSettingCard(self.autostore_card)

        self.tray_card = SwitchSettingCard(
            FluentIcon.MINIMIZE,
            "Zamykaj do zasobnika systemowego (tray)",
            "Przycisk X chowa okno do tray zamiast zamykać program - "
            "farmienie kart i idle działają dalej w tle",
            config.minimize_to_tray,
            parent=behavior_group,
        )
        behavior_group.addSettingCard(self.tray_card)
        root.addWidget(behavior_group)

        about_group = SettingCardGroup("O aplikacji", content)
        self.about_card = PushSettingCard(
            "Otwórz",
            FluentIcon.INFO,
            "SteamTools",
            "Wersja, autor, inspiracje, FAQ i sprawdzanie aktualizacji - "
            "zakładka Informacje",
            parent=about_group,
        )
        self.about_card.clicked.connect(self.openAboutRequested)
        about_group.addSettingCard(self.about_card)
        root.addWidget(about_group)

        root.addWidget(self._build_community_session_group(content))

        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        qconfig.themeChanged.connect(self._on_theme_changed)
        self.theme_card.optionChanged.connect(self._apply_theme)
        self._apply_theme()

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
        # resztą SettingCardGroup powyżej (Wygląd/Zachowanie/O aplikacji).
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
            "4. Skopiuj wartość ciasteczka \"steamLoginSecure\" (i opcjonalnie "
            "\"sessionid\")",
            howto_card,
        )
        howto_steps.setWordWrap(True)
        howto_steps.setTextColor("#606060", "#c0c0c0")
        howto_layout.addWidget(howto_steps)
        layout.addWidget(howto_card)

        saved = load_community_session()

        session_id_label = StrongBodyLabel("Ciasteczko sessionid", card)
        layout.addWidget(session_id_label)

        self.session_id_input = LineEdit(card)
        self.session_id_input.setPlaceholderText(
            "np. 6c5019dfb3709248f09d92ea (token CSRF, 24 znaki hex)"
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

        wrapper_layout.addWidget(card)
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

    def _apply_theme(self) -> None:
        mapping = {"Light": Theme.LIGHT, "Dark": Theme.DARK, "Auto": Theme.AUTO}
        setTheme(mapping.get(config.dark_mode.value, Theme.AUTO))

    def _on_theme_changed(self, *_args) -> None:
        pass
