import json

import pytest


@pytest.fixture
def config_mod(home):
    import config
    return config


def test_fresh_install_uses_aether_term_dir(config_mod):
    cfg = config_mod.Config()
    assert config_mod.APP_NAME == "Aether Term"
    assert cfg.app_data_dir == config_mod._app_data_base() / "Aether Term"
    assert cfg.mode == "VARA FM"


def test_vara_term_settings_are_migrated_and_left_in_place(config_mod):
    legacy = config_mod._app_data_base() / "VARA Term"
    legacy.mkdir(parents=True)
    (legacy / "settings.json").write_text(json.dumps(
        {"my_callsign": "KK4ODA", "target_history": ["W1AW-5"]}))
    (legacy / "passwords.enc").write_bytes(b"secret")
    (legacy / "hamlib" / "bin").mkdir(parents=True)

    cfg = config_mod.Config()

    assert cfg.get("my_callsign") == "KK4ODA"
    assert (cfg.app_data_dir / "passwords.enc").read_bytes() == b"secret"
    assert (cfg.app_data_dir / "hamlib" / "bin").is_dir()
    assert (legacy / "settings.json").exists()


def test_existing_aether_term_dir_is_not_overwritten(config_mod):
    base = config_mod._app_data_base()
    (base / "VARA Term").mkdir(parents=True)
    (base / "VARA Term" / "settings.json").write_text(json.dumps({"my_callsign": "OLD"}))
    (base / "Aether Term").mkdir()
    (base / "Aether Term" / "settings.json").write_text(json.dumps({"my_callsign": "NEW"}))
    assert config_mod.Config().get("my_callsign") == "NEW"


@pytest.mark.parametrize("mode,is_hf,is_aether,band,prefix_port", [
    ("VARA FM", False, False, False, "vara_fm_cmd_port"),
    ("VARA HF", True, False, True, "vara_hf_cmd_port"),
    ("Aether HF", False, True, True, "aether_cmd_port"),
])
def test_mode_properties(config_mod, mode, is_hf, is_aether, band, prefix_port):
    cfg = config_mod.Config()
    cfg.set("vara_mode", mode)
    cfg.set(prefix_port, 9100)
    assert (cfg.is_hf, cfg.is_aether, cfg.is_hf_band) == (is_hf, is_aether, band)
    assert cfg.cmd_port == 9100


def test_aether_bandwidth_and_ptt(config_mod):
    cfg = config_mod.Config()
    cfg.set("vara_mode", "Aether HF")
    assert cfg.session_bandwidth == 2300
    assert not cfg.needs_host_ptt          # Aether HF keys the radio itself
    cfg.set("aether_host_ptt", True)
    assert cfg.needs_host_ptt
    cfg.set("aether_host", "10.0.0.5")
    cfg.set("aether_control_port", 9515)
    assert cfg.aether_control_url == "http://10.0.0.5:9515"

    cfg.set("vara_mode", "VARA HF")
    cfg.set("hf_bandwidth", 2750)
    assert cfg.session_bandwidth == 2750
    assert cfg.needs_host_ptt


def test_password_store_identifiers_unchanged():
    """Changing these would make every saved station password unreadable."""
    import passwords
    assert passwords._SERVICE_NAME == "VARA Term"
    assert passwords._KEYRING_KEY == "vterm_master_key"


def test_new_configs_do_not_share_profile_lists(home):
    """A profile added to one fresh Config used to land in the module's
    defaults, and so in every Config created after it."""
    from config import Config, DEFAULT_SETTINGS
    Config().add_profile({"name": "X"})
    assert Config().get_profiles() == []
    assert DEFAULT_SETTINGS["profiles"] == []


def test_unreadable_settings_are_kept_not_overwritten(home):
    """A settings.json that fails to parse used to be replaced by the
    defaults at the next save, losing profiles, macros and history."""
    from config import Config
    cfg = Config()
    cfg.save()
    cfg._path.write_text('{"my_callsign": "KK4ODA", "profiles": [', encoding="utf-8")
    again = Config()
    assert again.load_error and "unreadable" in again.load_error
    kept = list(cfg._dir.glob("settings.json.unreadable-*"))
    assert len(kept) == 1 and '"KK4ODA"' in kept[0].read_text()
    again.save()
    assert kept[0].exists()


def test_unreadable_passwords_are_kept_not_overwritten(home, monkeypatch):
    """A passwords.enc that fails to decrypt used to be overwritten by the
    next saved password, losing every other one."""
    import passwords
    from config import Config
    from passwords import PasswordStore
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)
    d = Config().app_data_dir
    store = PasswordStore(d)
    store.set_password("W1AW-5", "one")
    (d / "passwords.enc").write_bytes(b"not a fernet token")
    store2 = PasswordStore(d)
    assert store2.load_error
    store2.set_password("KE4QCM-7", "two")
    kept = list(d.glob("passwords.enc.unreadable-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == b"not a fernet token"
    assert PasswordStore(d).get_password("KE4QCM-7") == "two"


def test_save_leaves_no_partial_file(home, monkeypatch):
    """Settings are written to a temporary file and renamed into place."""
    import os
    from config import Config
    cfg = Config()
    cfg.set("my_callsign", "KK4ODA")
    cfg.save()
    before = cfg._path.read_text()

    def failing_replace(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", failing_replace)
    cfg.set("my_callsign", "W1AW")
    cfg.save()                                   # logged, not raised
    assert cfg._path.read_text() == before


def test_cleared_modem_path_stays_cleared(home):
    """The v1.1 exe-path migration ran at every start, putting back a
    path (and auto-launch) the user had cleared."""
    from config import Config
    cfg = Config()
    cfg.set("vara_fm_exe_path", "")
    cfg.set("vara_fm_auto_launch", False)
    cfg.save()
    again = Config()
    assert again.get("vara_fm_exe_path") == ""
    assert again.get("vara_fm_auto_launch") is False


def test_hamlib_archive_cannot_write_outside_its_folder(tmp_path):
    """Archive entries like "../x" were written wherever they pointed."""
    import io
    import zipfile
    import pytest
    from vara.hamlib_download import HamlibDownloader
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bin/rigctld.exe", b"ok")
        zf.writestr("../../escaped.txt", b"bad")
    dl = HamlibDownloader(install_dir=tmp_path / "hamlib")
    (tmp_path / "hamlib").mkdir()
    with pytest.raises(RuntimeError, match="outside the install folder"):
        dl._extract_zip(io.BytesIO(buf.getvalue()))
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()
