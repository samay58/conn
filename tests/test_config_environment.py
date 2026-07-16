from conn.config import load_config


def test_server_port_can_be_bound_to_lab_port(monkeypatch, tmp_path):
    monkeypatch.setenv("CONN_SERVER_PORT", "18787")

    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 18787


def test_invalid_server_port_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CONN_SERVER_PORT", "8787oops")

    try:
        load_config(tmp_path / "missing.toml")
    except ValueError as error:
        assert "CONN_SERVER_PORT" in str(error)
    else:
        raise AssertionError("invalid CONN_SERVER_PORT was accepted")


def test_data_directory_can_be_isolated_by_environment(monkeypatch, tmp_path):
    data_dir = tmp_path / "lab-data"
    monkeypatch.setenv("CONN_DATA_DIR", str(data_dir))

    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.data_dir == data_dir
