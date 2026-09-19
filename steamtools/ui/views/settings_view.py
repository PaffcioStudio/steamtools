"""Widok "Ustawienia" - motyw, zachowanie programu, informacje o aplikacji.

Sekcja Steam Community (steamLoginSecure/sessionid) mieszka w osobnym
widoku - ui/views/account_view.py (zakładka "Konto" w sidebarze) - była
tu wcześniej, ale schowana na dole Ustawień była praktycznie niewidoczna
dla nowych userów."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel,
    CaptionLabel,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
    OptionsSettingCard,
    PushSettingCard,
    IconWidget,
    FluentIcon,
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
from steamtools.core.config import settings_file_path


class AppConfig(QConfig):
    dark_mode = OptionsConfigItem(
        "Appearance", "DarkMode", "Auto", OptionsValidator(["Light", "Dark", "Auto"])
    )
    auto_store = ConfigItem("Achievements", "AutoStore", False, BoolValidator())
    # Domyślnie WYŁĄCZONE - pierwsze wrażenie ma znaczenie: ktoś kto
    # odpali program na chwilę (np. sprawdzić/odblokować kilka osiągnięć)
    # i kliknie X spodziewa się, że program się zamknie, a nie że
    # "zniknie" do tray bez wyjaśnienia. Kto faktycznie chce farmić karty
    # w tle, ten dowie się o tej opcji naturalnie: gdy trwa farmienie a ta
    # opcja jest wyłączona, dialog ostrzegawczy przy X (patrz
    # _ClosingWhileIdlingDialog) i tak zaproponuje "Ukryj w tray" jako
    # jedną z opcji, więc odkrycie tej funkcji nie wymaga grzebania w
    # Ustawieniach.
    minimize_to_tray = ConfigItem("Behavior", "MinimizeToTray", False, BoolValidator())
    # Oba domyślnie włączone - user farmiący karty w tle (zminimalizowane
    # okno/tray) chce wiedzieć, że coś się skończyło, bez konieczności
    # ciągłego zaglądania do zakładki "Farma kart". Wymaga systemowego
    # traya (patrz MainWindow._build_tray_icon) - bez niego powiadomienia
    # po prostu się nie pokażą, niezależnie od tych ustawień.
    notify_game_cards_exhausted = ConfigItem(
        "Notifications", "NotifyGameCardsExhausted", True, BoolValidator()
    )
    notify_all_games_finished = ConfigItem(
        "Notifications", "NotifyAllGamesFinished", True, BoolValidator()
    )


config = AppConfig()
# BEZ tego wywołania `qconfig.get`/`qconfig.set` (używane wewnątrz każdego
# SwitchSettingCard/OptionsSettingCard) działały WYŁĄCZNIE w pamięci -
# qconfig to globalny singleton z qfluentwidgets, i dopóki nikt mu nie
# powie, które ConfigItem trzymać i w jakim pliku, .set() nie ma gdzie
# zapisać zmiany na dysk. Efekt: przełączniki wyglądały jakby działały w
# bieżącej sesji, ale każdy restart programu czytał `config.minimize_to_tray`
# świeżo stworzone z wartością domyślną z definicji klasy wyżej, ignorując
# to co user ustawił poprzednio. Plik trzymany w tym samym katalogu XDG co
# reszta stanu aplikacji (idle_queue.json, community_session.json).
qconfig.load(str(settings_file_path()), config)


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

        self.notify_exhausted_card = SwitchSettingCard(
            FluentIcon.RINGER,
            "Powiadomienie o wyczerpaniu kart w grze",
            "Pokaż powiadomienie na pulpicie, gdy farmiona gra osiągnie "
            "0 pozostałych kart",
            config.notify_game_cards_exhausted,
            parent=behavior_group,
        )
        behavior_group.addSettingCard(self.notify_exhausted_card)

        self.notify_finished_card = SwitchSettingCard(
            FluentIcon.COMPLETED,
            "Powiadomienie o zakończeniu farmienia",
            "Pokaż powiadomienie na pulpicie, gdy wszystkie gry w kolejce "
            "zostaną wyfarmione",
            config.notify_all_games_finished,
            parent=behavior_group,
        )
        behavior_group.addSettingCard(self.notify_finished_card)

        root.addWidget(behavior_group)

        # qfluentwidgets domyślnie podpisuje przełączniki angielskim "On"/
        # "Off" niezależnie od reszty (polskiego) interfejsu. setOnText/
        # setOffText NIE wystarczy samo w sobie - SwitchSettingCard.setValue()
        # (wołane przy KAŻDEJ zmianie przełącznika, bo jest podpięte pod
        # configItem.valueChanged) na końcu twardo nadpisuje tekst z
        # powrotem na self.tr('On')/self.tr('Off'), więc bez tej dodatkowej
        # obsługi teksty wracałyby do angielskich zaraz po pierwszym
        # kliknięciu przełącznika przez usera. Dlatego dla każdej karty
        # łapiemy też checkedChanged i wymuszamy nasz tekst po fakcie.
        def _polish_switch_text(card: SwitchSettingCard) -> None:
            card.switchButton.setOnText("Wł")
            card.switchButton.setOffText("Wył")

        for switch_card in (
            self.autostore_card,
            self.tray_card,
            self.notify_exhausted_card,
            self.notify_finished_card,
        ):
            _polish_switch_text(switch_card)
            switch_card.switchButton.checkedChanged.connect(
                lambda _checked, c=switch_card: _polish_switch_text(c)
            )

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

        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        qconfig.themeChanged.connect(self._on_theme_changed)
        self.theme_card.optionChanged.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mapping = {"Light": Theme.LIGHT, "Dark": Theme.DARK, "Auto": Theme.AUTO}
        setTheme(mapping.get(config.dark_mode.value, Theme.AUTO))

    def _on_theme_changed(self, *_args) -> None:
        pass
