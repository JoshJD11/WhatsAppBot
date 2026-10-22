"""Tests for scripts/start.sh with fake uvicorn and ngrok executables."""

import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "start.sh"

FAKE_UVICORN = f"""#!{sys.executable}
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""

FAKE_NGROK = """#!/usr/bin/env bash
echo "$@" > "$NGROK_ARGS_FILE"
"""


def _executable(path: Path, content: str) -> Path:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def sandbox(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "ngrok", FAKE_NGROK)
    uvicorn = _executable(tmp_path / "uvicorn", FAKE_UVICORN)
    env_file = tmp_path / ".env"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ENV_FILE": str(env_file),
        "UVICORN": str(uvicorn),
        "PORT": str(_free_port()),
        "NGROK_ARGS_FILE": str(tmp_path / "ngrok_args"),
        "HOME": str(tmp_path),
        "NGROK_FALLBACK": str(tmp_path / "no-ngrok-here"),
    }
    return tmp_path, env_file, env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


def test_script_starts_bot_then_ngrok_with_the_static_domain(sandbox):
    tmp_path, env_file, env = sandbox
    env_file.write_text("WHATSAPP_TOKEN=secret\nNGROK_DOMAIN=bosca-test.ngrok-free.app\n")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "ngrok_args").read_text().split() == [
        "http",
        "--url=bosca-test.ngrok-free.app",
        env["PORT"],
    ]
    assert "https://bosca-test.ngrok-free.app/webhook" in result.stdout
    assert "secret" not in result.stdout + result.stderr


def test_script_cleans_quotes_scheme_and_trailing_slash(sandbox):
    tmp_path, env_file, env = sandbox
    env_file.write_text('NGROK_DOMAIN="https://bosca-test.ngrok-free.app/"\n')
    assert _run(env).returncode == 0
    assert "--url=bosca-test.ngrok-free.app" in (tmp_path / "ngrok_args").read_text()


@pytest.mark.parametrize(
    "content,message",
    [
        (None, "not found"),
        ("WHATSAPP_TOKEN=x\n", "NGROK_DOMAIN is empty"),
        ("NGROK_DOMAIN=\n", "NGROK_DOMAIN is empty"),
        ("NGROK_DOMAIN=bad domain;rm -rf\n", "not a valid domain"),
    ],
)
def test_script_rejects_bad_configuration(sandbox, content, message):
    tmp_path, env_file, env = sandbox
    if content is not None:
        env_file.write_text(content)
    result = _run(env)
    assert result.returncode == 1
    assert message in result.stderr
    assert not (tmp_path / "ngrok_args").exists()


def test_script_requires_ngrok(sandbox):
    _, env_file, env = sandbox
    env_file.write_text("NGROK_DOMAIN=bosca-test.ngrok-free.app\n")
    env["PATH"] = "/usr/bin:/bin"
    result = _run(env)
    assert result.returncode == 1
    assert "ngrok is not installed" in result.stderr


def test_script_finds_ngrok_outside_path(sandbox):
    tmp_path, env_file, env = sandbox
    env_file.write_text("NGROK_DOMAIN=bosca-test.ngrok-free.app\n")
    env["PATH"] = "/usr/bin:/bin"
    env["NGROK_FALLBACK"] = str(tmp_path / "bin" / "ngrok")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "--url=bosca-test.ngrok-free.app" in (tmp_path / "ngrok_args").read_text()


def test_script_fails_if_bot_does_not_start(sandbox):
    tmp_path, env_file, env = sandbox
    env_file.write_text("NGROK_DOMAIN=bosca-test.ngrok-free.app\n")
    env["UVICORN"] = str(_executable(tmp_path / "broken_uvicorn", "#!/usr/bin/env bash\nexit 3\n"))
    result = _run(env)
    assert result.returncode == 1
    assert "stopped while starting" in result.stderr
    assert not (tmp_path / "ngrok_args").exists()
