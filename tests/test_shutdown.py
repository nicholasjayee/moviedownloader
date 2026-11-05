"""Ctrl+C should finish server cleanup and return without a Python traceback."""

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from moviebox_app.cli import main


def test_launcher_handles_keyboard_interrupt_after_server_cleanup(settings, monkeypatch):
    listener = MagicMock()
    server = MagicMock()
    server.run.side_effect = KeyboardInterrupt
    monkeypatch.setattr("moviebox_app.cli.Settings", lambda: settings)
    monkeypatch.setattr("moviebox_app.cli.reserve_port", lambda *args: (listener, 8765))
    monkeypatch.setattr("moviebox_app.cli.uvicorn.Server", lambda *args: server)
    main([])
    listener.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.skipif(os.name == "nt", reason="POSIX terminal process-group signals")
@pytest.mark.parametrize("dev", [False, True])
def test_ctrl_c_shuts_down_server_and_reload_worker(tmp_path, dev):
    project = Path(__file__).resolve().parent.parent
    # Isolate the watcher from the active workspace and its dependency tree.
    shutil.copytree(
        project / "moviebox_app",
        tmp_path / "moviebox_app",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copyfile(project / "main.py", tmp_path / "main.py")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ | {
        "MOVIEBOX_HOST": "127.0.0.1",
        "MOVIEBOX_DATA_DIR": str(tmp_path / "data"),
        "MOVIEBOX_DOWNLOAD_DIR": str(tmp_path / "downloads"),
    }
    command = [sys.executable, "main.py", "--port", str(port)]
    if dev:
        command.append("--dev")
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            command,
            cwd=tmp_path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                log.seek(0)
                output = log.read()
                assert process.poll() is None, output
                if "Application startup complete." in output:
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"Server did not start:\n{output}")

            # Signal the whole group, as a real terminal does when Ctrl+C is pressed.
            os.killpg(process.pid, signal.SIGINT)
            assert process.wait(timeout=10) == 0
            log.seek(0)
            output = log.read()
            assert "Application shutdown complete." in output
            assert "Traceback" not in output
            assert "CancelledError" not in output
            assert "KeyboardInterrupt" not in output
            urls = re.findall(r"http://127\.0\.0\.1:(\d+)", output)
            assert urls, output
            with socket.socket() as connection:
                connection.settimeout(1)
                assert connection.connect_ex(("127.0.0.1", int(urls[0]))) != 0
            if dev:
                assert "Stopping reloader process" in output
                worker_ids = re.findall(r"Started server process \[(\d+)\]", output)
                assert worker_ids
                for worker_id in worker_ids:
                    with pytest.raises(ProcessLookupError):
                        os.kill(int(worker_id), 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
