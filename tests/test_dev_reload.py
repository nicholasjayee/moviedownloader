"""Exercise the real reload subprocess against a disposable copy of the app."""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def test_dev_reloads_template_and_retains_fallback_port(tmp_path):
    project = Path(__file__).resolve().parent.parent
    shutil.copytree(
        project / "moviebox_app",
        tmp_path / "moviebox_app",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copyfile(project / "main.py", tmp_path / "main.py")
    env = os.environ | {
        "MOVIEBOX_HOST": "127.0.0.1",
        "MOVIEBOX_DATA_DIR": str(tmp_path / "data"),
        "MOVIEBOX_DOWNLOAD_DIR": str(tmp_path / "downloads"),
    }
    with socket.create_server(("127.0.0.1", 0)) as occupied:
        start = occupied.getsockname()[1]
        if start == 65535:
            pytest.skip("OS selected the last port")
        with (tmp_path / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "main.py", "--dev", "--port", str(start)],
                cwd=tmp_path,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:

                    def wait_for_page(text):
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            log.seek(0)
                            output = log.read()
                            assert process.poll() is None, output
                            urls = [
                                line.split("Local:", 1)[1].strip()
                                for line in output.splitlines()
                                if line.strip().startswith("Local:")
                            ]
                            if urls:
                                try:
                                    response = client.get(urls[0])
                                    if response.status_code == 200 and text in response.text:
                                        return urls[0]
                                except httpx.HTTPError:
                                    pass
                            time.sleep(0.1)
                        pytest.fail(f"Development server did not serve {text!r}:\n{output}")

                    url = wait_for_page("Add a movie")
                    assert int(url.rsplit(":", 1)[1]) > start
                    log.seek(0)
                    network_urls = [
                        line.split("Network:", 1)[1].strip()
                        for line in log.read().splitlines()
                        if line.strip().startswith("Network: http://")
                    ]
                    for network_url in network_urls:
                        assert client.get(f"{network_url}/api/health").status_code == 200
                    template = tmp_path / "moviebox_app/web/templates/index.html"
                    template.write_text(template.read_text().replace("Add a movie", "Add a film"))
                    assert wait_for_page("Add a film") == url
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
