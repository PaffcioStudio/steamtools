import pytest

from steamtools.core import badges

ROW = '''
<div class="badge_row">
  <a class="badge_row_overlay" href="https://steamcommunity.com/my/gamecards/{app}/"></a>
  <div class="badge_title">{name}View details</div>
  <div class="badge_title_stats_content"><span class="progress_info_bold">{progress}</span></div>
</div>
'''


def test_parse_badges_extracts_remaining_cards_and_cleans_name():
    html = (
        ROW.format(app=251570, name="7 Days to Die", progress="3 card drops remaining")
        + ROW.format(app=730, name="Counter-Strike 2", progress="No card drops remaining")
        + ROW.format(app=570, name="Dota 2", progress="1 card drop remaining")
    )
    result = badges._parse_badges_html(html)
    assert [(r.app_id, r.name, r.cards_remaining) for r in result] == [
        (251570, "7 Days to Die", 3),
        (570, "Dota 2", 1),
    ]


@pytest.mark.parametrize(
    "count,expected",
    [(0, "Brak kart"), (1, "1 karta"), (2, "2 karty"), (4, "4 karty"), (5, "5 kart"),
     (12, "12 kart"), (22, "22 karty"), (112, "112 kart")],
)
def test_polish_plural(count, expected):
    assert badges.format_cards_count(count) == expected


def test_steam_id_from_cookie():
    sid = "76561198012345678"
    assert badges.extract_steam_id64_from_cookie(f"{sid}%7C%7Cabcdef") == sid
    assert badges.extract_steam_id64_from_cookie(f"{sid}||abcdef") == sid
    assert badges.extract_steam_id64_from_cookie("garbage") is None
    assert badges.extract_steam_id64_from_cookie("123||abc") is None


def test_login_state_detection():
    assert badges._detect_login_state('g_steamID = "76561198012345678";') is True
    assert badges._detect_login_state("g_steamID = false;") is False
    assert badges._detect_login_state("<html>maintenance</html>") is None


def test_fetch_follows_pagination_until_no_new_rows(monkeypatch):
    pages = {
        1: ROW.format(app=1, name="A", progress="2 card drops remaining")
        + ROW.format(app=2, name="B", progress="No card drops remaining"),
        2: ROW.format(app=3, name="C", progress="1 card drop remaining"),
        3: ROW.format(app=3, name="C", progress="1 card drop remaining"),  # Steam powtarza ostatnią
    }
    requested = []

    def fake_load(cookie, session_id="", page=1):
        requested.append(page)
        return pages.get(page, ""), None

    monkeypatch.setattr(badges, "_load_badges_page", fake_load)
    monkeypatch.setattr(badges.time, "sleep", lambda s: None)
    result = badges.fetch_badge_progress("cookie")
    assert [(r.app_id, r.cards_remaining) for r in result] == [(1, 2), (3, 1)]
    assert requested == [1, 2, 3]
