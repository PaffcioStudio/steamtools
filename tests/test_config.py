from steamtools.core import config


def test_idle_queue_roundtrip():
    state = config.IdleQueueState(entries=[config.SavedIdleEntry(1, "A", True), config.SavedIdleEntry(2, "B")])
    config.save_idle_queue(state)
    loaded = config.load_idle_queue()
    assert [(e.app_id, e.name, e.was_paused) for e in loaded.entries] == [(1, "A", True), (2, "B", False)]
    config.clear_idle_queue()
    assert config.load_idle_queue().entries == []


def test_idle_queue_corrupt_file_gives_empty_state():
    config._config_dir().mkdir(parents=True)
    config._idle_queue_path().write_text("{nie json")
    assert config.load_idle_queue().entries == []


def test_community_session_roundtrip_and_permissions():
    assert not config.load_community_session().is_configured()
    config.save_community_session(config.CommunitySession("cookie", "sid"))
    session = config.load_community_session()
    assert (session.session_cookie, session.session_id) == ("cookie", "sid")
    assert oct(config._community_session_path().stat().st_mode & 0o777) == "0o600"
    config.clear_community_session()
    assert not config.load_community_session().is_configured()


def test_owned_games_cache_roundtrip_and_corrupt():
    assert config.load_owned_games_cache() == ("", [])
    config.save_owned_games_cache("7656", [(1, "A"), (2, "B")])
    assert config.load_owned_games_cache() == ("7656", [(1, "A"), (2, "B")])
    config._owned_games_cache_path().write_text("[]")
    assert config.load_owned_games_cache() == ("", [])
