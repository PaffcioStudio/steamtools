from steamtools.core.library import parse_vdf

LIBRARYFOLDERS = '''
"libraryfolders"
{
    "0"
    {
        "path"      "/home/u/.steam/steam"
        "apps"
        {
            "251570"    "1234"
        }
    }
    "1"
    {
        "path"      "/media/u/Dysk/SteamLibrary"
        "apps"
        {
            "730"   "99"
        }
    }
}
'''


def test_nested_sections_keep_their_own_values():
    data = parse_vdf(LIBRARYFOLDERS)
    assert data["0"]["path"] == "/home/u/.steam/steam"
    assert data["1"]["path"] == "/media/u/Dysk/SteamLibrary"
    assert data["1"]["apps"] == {"730": "99"}


def test_appmanifest_flat():
    data = parse_vdf('"AppState"\n{\n\t"appid"\t"251570"\n\t"name"\t"7 Days to Die"\n}\n')
    assert data == {"appid": "251570", "name": "7 Days to Die"}


def test_comments_and_escapes():
    text = '"x"\n{\n// komentarz\n"a" "b \\"c\\""\n}\n'
    assert parse_vdf(text) == {"a": 'b "c"'}


def test_empty_and_garbage_do_not_raise():
    assert parse_vdf("") == {}
    assert isinstance(parse_vdf('"a" {'), dict)
