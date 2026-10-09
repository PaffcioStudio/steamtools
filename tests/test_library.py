from pathlib import Path

import steamtools.core.library as lib


def _manifest(folder: Path, app_id: int, name: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"appmanifest_{app_id}.acf").write_text(
        f'"AppState"\n{{\n"appid" "{app_id}"\n"name" "{name}"\n"installdir" "x"\n"SizeOnDisk" "5"\n}}\n',
        encoding="utf-8",
    )


def test_scan_filters_tools_tmp_and_duplicates(tmp_path, monkeypatch):
    a = tmp_path / "lib_a" / "steamapps"
    b = tmp_path / "lib_b" / "steamapps"
    _manifest(a, 251570, "7 Days to Die")
    _manifest(a, 1493710, "Steam Linux Runtime 3.0 (sniper)")
    _manifest(a, 2348590, "Proton 8.0")
    _manifest(b, 251570, "7 Days to Die")  # duplikat w drugiej bibliotece
    _manifest(b, 730, "Counter-Strike 2")
    (a / "appmanifest_999.acf.123456.tmp").write_text("junk")
    monkeypatch.setattr(lib, "find_library_folders", lambda: [a, b])

    games = lib.scan_installed_games()
    assert [g.app_id for g in games] == [251570, 730]  # sort po nazwie, bez narzędzi i duplikatu


def test_find_library_folders_reads_libraryfolders_vdf(tmp_path, monkeypatch):
    steam = tmp_path / "steam"
    extra = tmp_path / "disk" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (extra / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{steam}"\n}}\n"1"\n{{\n"path" "{extra}"\n}}\n}}\n'
    )
    monkeypatch.setattr(lib, "_default_steam_paths", lambda: [steam])
    folders = lib.find_library_folders()
    assert folders == [steam / "steamapps", extra / "steamapps"]


def test_merge_library_marks_installed_and_drops_tools():
    installed = [lib.InstalledGame(251570, "7 Days to Die", "x", Path("."))]
    owned = [(251570, "7 Days To Die"), (730, "Counter-Strike 2"), (1493710, "Steam Linux Runtime 3.0 (sniper)")]
    merged = lib.merge_library(installed, owned)
    assert {g.app_id: g.installed for g in merged} == {251570: True, 730: False}
    assert next(g for g in merged if g.app_id == 251570).name == "7 Days to Die"  # nazwa z manifestu


def test_merge_keeps_installed_missing_from_owned():
    installed = [lib.InstalledGame(5, "Family Game", "x", Path("."))]
    assert [g.app_id for g in lib.merge_library(installed, [])] == [5]
