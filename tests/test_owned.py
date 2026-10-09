import html
import json

from steamtools.core import owned

GAMES = [
    {"appid": 251570, "name": "7 Days to Die"},
    {"appid": "730", "name": "Counter-Strike 2"},
    {"appid": 1, "name": ""},
    {"nie": "gra"},
]


def test_parse_html_data_attribute():
    page = '<div data-profile-gameslist="%s"></div>' % html.escape(json.dumps({"rgGames": GAMES}))
    result = owned.parse_owned_games_html(page)
    assert [(g.app_id, g.name) for g in result] == [
        (251570, "7 Days to Die"), (730, "Counter-Strike 2"), (1, "AppID 1"),
    ]


def test_parse_html_legacy_script_and_missing():
    assert len(owned.parse_owned_games_html("<script>var rgGames = %s;</script>" % json.dumps(GAMES))) == 3
    assert owned.parse_owned_games_html("<html>nic</html>") is None
    assert owned.parse_owned_games_html('<div data-profile-gameslist="%s"></div>' % html.escape('{"rgGames":[]}')) == []


def test_parse_xml():
    xml = ("<gamesList><games><game><appID>730</appID><name><![CDATA[Counter-Strike 2]]></name></game>"
           "<game><appID>570</appID><name>Dota 2</name></game></games></gamesList>")
    assert [(g.app_id, g.name) for g in owned.parse_owned_games_xml(xml)] == [(730, "Counter-Strike 2"), (570, "Dota 2")]
    assert owned.parse_owned_games_xml("<response><error>x</error></response>") is None


def test_fetch_prefers_web_api_and_dedups(monkeypatch):
    def fake_json(url, cookie_header=""):
        if "ajaxgetasyncconfig" in url:
            return {"data": {"webapi_token": "tok"}}
        return {"response": {"games": [{"appid": 2, "name": "B"}, {"appid": 1, "name": "a"}, {"appid": 2, "name": "dup"}]}}

    monkeypatch.setattr(owned, "_get_json", fake_json)
    sid, games = owned.fetch_owned_games("76561198012345678%7C%7Cabc")
    assert sid == "76561198012345678"
    assert [(g.app_id, g.name) for g in games] == [(1, "a"), (2, "B")]


def test_fetch_falls_back_to_html(monkeypatch):
    monkeypatch.setattr(owned, "_get_json", lambda *a, **k: None)
    page = '<div data-profile-gameslist="%s"></div>' % html.escape(json.dumps({"rgGames": GAMES[:1]}))
    monkeypatch.setattr(owned, "load_community_page", lambda *a, **k: (page, None))
    _, games = owned.fetch_owned_games("76561198012345678%7C%7Cabc")
    assert [g.app_id for g in games] == [251570]


def test_fetch_bad_cookie_means_expired():
    import pytest
    with pytest.raises(owned.SteamSessionExpiredError):
        owned.fetch_owned_games("nie-cookie")
