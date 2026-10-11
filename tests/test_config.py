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
