import argparse
import errno
import json
import os
import socket
from unittest.mock import MagicMock

import pytest

from moviebox_app.cli import main, port_number, reserve_port


@pytest.mark.parametrize("value", ["0", "-1", "65536", "abc", "8.5"])
def test_rejects_invalid_ports(value):
    with pytest.raises(argparse.ArgumentTypeError):
        port_number(value)


def test_busy_port_is_skipped_and_selected_port_stays_reserved():
    with socket.create_server(("127.0.0.1", 0)) as occupied:
        start = occupied.getsockname()[1]
        if start == 65535:
            pytest.skip("OS selected the last port")
        listener, port = reserve_port("127.0.0.1", start)
        with listener:
            assert port > start
            assert listener.getsockname()[1] == port
            with pytest.raises(OSError) as error:
                socket.create_server(("127.0.0.1", port))
            assert error.value.errno == errno.EADDRINUSE


def test_exhaustion_does_not_wrap_to_an_unrequested_port(monkeypatch):
    listener = MagicMock()
    listener.bind.side_effect = OSError(errno.EADDRINUSE, "occupied")
    monkeypatch.setattr(socket, "socket", lambda *args: listener)
    with pytest.raises(OSError, match="No available port"):
        reserve_port("127.0.0.1", 65535)


def test_permission_errors_are_reported_without_scanning_other_ports(monkeypatch):
    listener = MagicMock()
    listener.bind.side_effect = PermissionError(errno.EACCES, "denied")
    monkeypatch.setattr(socket, "socket", lambda *args: listener)
    with pytest.raises(PermissionError):
        reserve_port("127.0.0.1", 8765)


@pytest.mark.parametrize("args", [["--help"], ["9000", "--port", "9001"]])
def test_help_and_conflicting_options_exit_before_binding(args):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == (0 if args == ["--help"] else 2)


@pytest.mark.parametrize(
    "args, expected",
    [
        ([], 8765),
        (["9000"], 9000),
        (["--port", "9100"], 9100),
        (["-p", "9200"], 9200),
    ],
)
def test_port_options_and_reserved_socket_reach_server(args, expected, settings, monkeypatch):
    listener = MagicMock()
    server = MagicMock()
    server_factory = MagicMock(return_value=server)
    reserve = MagicMock(return_value=(listener, expected + 1))
    monkeypatch.setattr("moviebox_app.cli.Settings", lambda: settings)
    monkeypatch.setattr("moviebox_app.cli.reserve_port", reserve)
    monkeypatch.setattr("moviebox_app.cli.uvicorn.Server", server_factory)
    main(args)
    reserve.assert_called_once_with(settings.host, expected)
    assert server_factory.call_args.args[0].port == expected + 1
    server.run.assert_called_once_with(sockets=[listener])
    assert server_factory.call_args.args[0].reload is False


@pytest.mark.parametrize("args", [["--dev"], ["--dev", "-p", "9000"], ["9000", "--dev"]])
@pytest.mark.parametrize("existing_dirs", [True, False])
def test_dev_mode_supervises_server_with_reserved_socket(
    args, existing_dirs, settings, monkeypatch, capsys
):
    from uvicorn.supervisors.watchfilesreload import FileFilter

    if existing_dirs:
        settings.data_dir.mkdir()
        settings.download_dir.mkdir()
    listener = MagicMock()
    server = MagicMock()
    server_factory = MagicMock(return_value=server)
    supervisor = MagicMock()
    supervisor_factory = MagicMock(return_value=supervisor)
    reserve = MagicMock(return_value=(listener, 9001))
    monkeypatch.setenv("MOVIEBOX_ALLOWED_HOSTS", "[]")
    monkeypatch.setattr("moviebox_app.cli.network_addresses", lambda: ["192.168.1.42"])
    monkeypatch.setattr("moviebox_app.cli.Settings", lambda: settings)
    monkeypatch.setattr("moviebox_app.cli.reserve_port", reserve)
    monkeypatch.setattr("moviebox_app.cli.uvicorn.Server", server_factory)
    monkeypatch.setattr("moviebox_app.cli.ChangeReload", supervisor_factory)
    main(args)
    config = server_factory.call_args.args[0]
    assert config.reload is True
    assert config.port == 9001
    assert config.host == "0.0.0.0"
    reserve.assert_called_once_with("0.0.0.0", 9000 if "9000" in args else settings.port)
    output = capsys.readouterr().out
    assert "Local:   http://127.0.0.1:9001" in output
    assert "Network: http://192.168.1.42:9001" in output
    assert "192.168.1.42" in json.loads(os.environ["MOVIEBOX_ALLOWED_HOSTS"])
    supervisor_factory.assert_called_once_with(config, target=server.run, sockets=[listener])
    supervisor.run.assert_called_once_with()
    server.run.assert_not_called()
    listener.set_inheritable.assert_called_once_with(True)
    file_filter = FileFilter(config)
    for filename in [
        "cli.py",
        "web/templates/index.html",
        "web/static/app.css",
        "web/static/app.js",
    ]:
        assert file_filter(config.reload_dirs[0] / "moviebox_app" / filename)
    assert not file_filter(settings.download_dir / "sample.mp4")
    assert not file_filter(settings.data_dir / "moviebox.sqlite3")
    if existing_dirs:
        assert not file_filter(settings.data_dir / "ignored.py")
        assert not file_filter(settings.download_dir / "ignored.js")
