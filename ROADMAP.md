# ROADMAP - SteamTools

Cel: w pełni natywna, linuksowa alternatywa dla **SteamAchievementManager**
(osiągnięcia) i **idle_master_extended** (farm kart), bez Wine, bez .NET,
oparta na PyQt6 i prawdziwym Steamworks SDK przez ctypes.

Poniżej tylko to, co jeszcze zostało w planach do zrobienia. Numeracja etapów jest zachowana z
wcześniejszych moich wersji planu. Zapraszam do lekturki ;)

## Etap 1 - Solidność achievement managera

- [ ] Statystyki liczbowe (nie tylko osiągnięcia) - UI do przeglądu i edycji
      `GetStatInt32`/`GetStatFloat` per gra. Steamworks nie pozwala wylistować
      nazw statystyk, więc potrzebny jest parser schematu z
      `appcache/stats/UserGameStatsSchema_<appid>.bin` (binarny format
      KeyValues), tak jak robi to SAM.
- [ ] Obsługa `ResetAllStats` z wyraźnym, osobnym potwierdzeniem (operacja
      destrukcyjna). Do zrobienia razem ze statystykami.

## Etap 2 - Integracja z biblioteką i danymi Steam

- [ ] Ustawienia: opcjonalny Steam Web API key jako stabilniejsze źródło listy
      gier. Obecnie lista pochodzi z tokenu sesji Steam Community
      (`core/owned.py`), więc ten punkt ma niski priorytet.

## Etap 3 - UX i stabilność

- [ ] Ujednolicenie stylu wizualnego (paleta, QSS) z pozostałymi projektami
      opartymi na PyQt6-Fluent-Widgets, jeśli powstanie wspólny motyw.
- [ ] i18n - wyciągnięcie tekstów UI z kodu do plików tłumaczeń (PL jako język
      domyślny), żeby nie było hardkodowanych stringów.

## Etap 4 - Packaging i dystrybucja

- [ ] Rozważyć AUR i Flathub jako dodatkowe kanały dystrybucji (opcjonalne,
      niski priorytet).

## Etap 5 - Rzeczy "nice to have"

- [ ] Statystyki i wykresy czasu idlowania (nawiązanie do `frmStatistics.cs`
      z idle_master_extended).
- [ ] Blacklista/whitelista gier do auto-idle (jak `frmBlacklist.cs` i
      `frmWhitelist.cs` w oryginale), np. pomijanie gier early-access bez
      kart w trybie "Sprawdź i farm wszystkie".
- [ ] Eksport i import konfiguracji (kolejka idle, ustawienia) między
      maszynami.

---
