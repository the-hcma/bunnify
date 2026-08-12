"""Start and stop the installed Bunnify server for the CLI."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from app.client import check_health


def ensure_local_server(
    *,
    port: int | None,
    pid_dir: Path,
    bookmarks: Path | None = None,
    timeout_s: float = 60,
) -> tuple[str, int]:
    """Return a healthy local server URL, starting the server when necessary."""
    if port is not None and not 0 <= port <= 65535:
        raise ValueError("Local server port must be between 0 and 65535")

    selected_port = port
    if selected_port is None:
        default_url = "http://127.0.0.1:8000"
        if check_health(default_url):
            return default_url, 8000
        selected_port = 8000 if port_is_free(8000) else 0

    if selected_port:
        base_url = f"http://127.0.0.1:{selected_port}"
        if check_health(base_url):
            return base_url, selected_port

    pid_dir.mkdir(parents=True, exist_ok=True)
    port_file = pid_dir / ".bunnify.port"
    if selected_port == 0:
        port_file.unlink(missing_ok=True)

    command = [
        sys.executable,
        "-m",
        "app.server_cli",
        "--port",
        str(selected_port),
        "--pid-dir",
        str(pid_dir),
        "--noninteractive",
    ]
    if bookmarks is not None:
        command.extend(["--bookmarks", str(bookmarks)])

    deadline = time.monotonic() + timeout_s
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=max(0.1, deadline - time.monotonic()),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Timed out starting the local Bunnify server after {timeout_s:g}s"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Local Bunnify server failed to start{suffix}")

    actual_port = selected_port
    while actual_port == 0 and time.monotonic() < deadline:
        try:
            actual_port = int(port_file.read_text(encoding="utf-8").strip())
        except OSError, ValueError:
            time.sleep(0.1)

    if not actual_port:
        raise RuntimeError(
            f"Local Bunnify server did not report its port in {port_file}"
        )

    base_url = f"http://127.0.0.1:{actual_port}"
    while time.monotonic() < deadline:
        if check_health(base_url):
            return base_url, actual_port
        time.sleep(0.1)
    raise RuntimeError(
        f"Local Bunnify server at {base_url} did not become healthy "
        f"within {timeout_s:g}s"
    )


def stop_local_server(pid_dir: Path) -> None:
    """Stop the managed local server associated with ``pid_dir``."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.server_cli",
            "--stop",
            "--pid-dir",
            str(pid_dir),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Failed to stop the local Bunnify server{suffix}")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True
