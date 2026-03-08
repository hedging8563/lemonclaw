"""Runtime helpers for the WhatsApp Node.js bridge."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from lemonclaw.config.loader import get_data_dir
from lemonclaw.config.schema import WhatsAppConfig

_BRIDGE_STATE_FILE = "whatsapp-bridge-state.json"
_BRIDGE_LOG_FILE = "logs/whatsapp-bridge.log"


class WhatsAppBridgeError(RuntimeError):
    """Raised when the WhatsApp bridge cannot be prepared or started."""


def get_bridge_state_path() -> Path:
    return get_data_dir() / _BRIDGE_STATE_FILE


def get_whatsapp_auth_dir() -> Path:
    return get_data_dir() / "whatsapp-auth"


def get_bridge_log_path() -> Path:
    return get_data_dir() / _BRIDGE_LOG_FILE


def _bridge_source_dir() -> Path:
    pkg_bridge = Path(__file__).parent.parent / "bridge"
    src_bridge = Path(__file__).parent.parent.parent / "bridge"
    if (pkg_bridge / "package.json").exists():
        return pkg_bridge
    if (src_bridge / "package.json").exists():
        return src_bridge
    raise WhatsAppBridgeError("Bridge source not found. Reinstall lemonclaw.")


def get_bridge_dir() -> Path:
    return get_data_dir() / "bridge"


def ensure_bridge_ready() -> Path:
    bridge_dir = get_bridge_dir()
    source = _bridge_source_dir()
    built_entry = bridge_dir / "dist" / "index.js"
    if built_entry.exists():
        built_mtime = built_entry.stat().st_mtime
        source_files = [p for p in source.rglob("*") if p.is_file()]
        if source_files and max(p.stat().st_mtime for p in source_files) <= built_mtime:
            return bridge_dir

    if not shutil.which("npm"):
        raise WhatsAppBridgeError("npm not found. Please install Node.js >= 20.")

    bridge_dir.parent.mkdir(parents=True, exist_ok=True)
    if bridge_dir.exists():
        shutil.rmtree(bridge_dir)
    shutil.copytree(source, bridge_dir, ignore=shutil.ignore_patterns("node_modules", "dist"))

    try:
        subprocess.run(["npm", "install"], cwd=bridge_dir, check=True, capture_output=True, text=True)
        subprocess.run(["npm", "run", "build"], cwd=bridge_dir, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise WhatsAppBridgeError(f"Failed to build WhatsApp bridge: {detail[:400]}") from exc

    return bridge_dir


def _parse_bridge_endpoint(bridge_url: str) -> tuple[str, int]:
    parsed = urlparse(bridge_url)
    if parsed.scheme not in {"ws", "wss"}:
        raise WhatsAppBridgeError(f"Unsupported bridge URL scheme: {bridge_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3001
    return host, port


def is_bridge_reachable(bridge_url: str) -> bool:
    host, port = _parse_bridge_endpoint(bridge_url)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def build_bridge_env(config: WhatsAppConfig) -> dict[str, str]:
    bridge_url = config.bridge_url or "ws://localhost:3001"
    host, port = _parse_bridge_endpoint(bridge_url)
    if host not in {"127.0.0.1", "localhost"}:
        raise WhatsAppBridgeError("Only local bridge_url values are supported for WebUI pairing.")

    env = {**os.environ}
    env["AUTH_DIR"] = str(get_whatsapp_auth_dir())
    env["BRIDGE_PORT"] = str(port)
    env["BRIDGE_STATE_FILE"] = str(get_bridge_state_path())
    if config.bridge_token:
        env["BRIDGE_TOKEN"] = config.bridge_token
    return env


def start_bridge_process(config: WhatsAppConfig) -> None:
    bridge_dir = ensure_bridge_ready()
    env = build_bridge_env(config)
    state_path = get_bridge_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_state = state_path.with_suffix(".tmp")
    tmp_state.write_text(json.dumps({"status": "starting", "qr": None, "account": None, "pid": None, "updated_at": time.time()}))
    tmp_state.replace(state_path)

    log_path = get_bridge_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")
    subprocess.Popen(
        ["npm", "start"],
        cwd=bridge_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()


def read_bridge_state() -> dict[str, object]:
    path = get_bridge_state_path()
    if not path.exists():
        return {"status": "stopped", "qr": None, "account": None}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"status": "error", "qr": None, "account": None, "error": "Bridge state file is corrupt."}
    if not isinstance(data, dict):
        return {"status": "error", "qr": None, "account": None, "error": "Bridge state file is invalid."}
    account = data.get("account") if isinstance(data.get("account"), dict) else None
    return {
        "status": str(data.get("status") or "unknown"),
        "qr": data.get("qr"),
        "account": account,
        "pid": data.get("pid"),
        "error": data.get("error"),
        "updated_at": data.get("updated_at"),
    }


def stop_bridge_process(timeout: float = 5.0) -> bool:
    state = read_bridge_state()
    pid = state.get("pid")
    if not isinstance(pid, int):
        path = get_bridge_state_path()
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        path = get_bridge_state_path()
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return False

    deadline = time.time() + max(timeout, 0.5)
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True

    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def reset_whatsapp_pairing() -> None:
    stop_bridge_process()
    auth_dir = get_whatsapp_auth_dir()
    if auth_dir.exists():
        shutil.rmtree(auth_dir)
    state_file = get_bridge_state_path()
    if state_file.exists():
        state_file.unlink()


def disconnect_whatsapp() -> dict[str, object]:
    reset_whatsapp_pairing()
    return {"status": "disconnected", "qr": None, "account": None, "running": False}


def restart_whatsapp_pairing(config: WhatsAppConfig, *, wait_timeout: float = 20.0) -> dict[str, object]:
    reset_whatsapp_pairing()
    return get_whatsapp_pairing_state(config, start_if_needed=True, wait_timeout=wait_timeout)


def get_whatsapp_pairing_state(
    config: WhatsAppConfig,
    *,
    start_if_needed: bool = False,
    wait_timeout: float = 15.0,
) -> dict[str, object]:
    if not config.enabled:
        return {"status": "disabled", "qr": None, "account": None, "running": False}

    bridge_url = config.bridge_url or "ws://localhost:3001"
    running = is_bridge_reachable(bridge_url)

    if not running and start_if_needed:
        # This blocking wait is intentionally executed via asyncio.to_thread()
        # from the Settings API so the main event loop remains responsive.
        start_bridge_process(config)
        deadline = time.time() + max(wait_timeout, 1.0)
        while time.time() < deadline:
            state = read_bridge_state()
            status = str(state.get("status") or "unknown")
            running = is_bridge_reachable(bridge_url)
            if status in {"connected", "qr", "error"}:
                return {**state, "running": running}
            time.sleep(0.4)

    state = read_bridge_state()
    return {**state, "running": running}
