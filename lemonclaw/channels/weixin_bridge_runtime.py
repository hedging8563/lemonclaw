"""Runtime helpers for the Weixin Node.js bridge."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse

from lemonclaw.config.loader import get_data_dir
from lemonclaw.config.schema import WeixinConfig

_BRIDGE_STATE_FILE = "weixin-bridge-state.json"
_BRIDGE_LOG_FILE = "logs/weixin-bridge.log"


class WeixinBridgeError(RuntimeError):
    """Raised when the Weixin bridge cannot be prepared or started."""


def get_bridge_state_path() -> Path:
    return get_data_dir() / _BRIDGE_STATE_FILE


def get_weixin_accounts_dir() -> Path:
    return get_data_dir() / "weixin-accounts"


def get_weixin_media_dir() -> Path:
    return get_data_dir() / "weixin-media"


def get_bridge_log_path() -> Path:
    return get_data_dir() / _BRIDGE_LOG_FILE


def _bridge_source_dir() -> Path:
    pkg_bridge = Path(__file__).parent.parent / "bridge"
    src_bridge = Path(__file__).parent.parent.parent / "bridge"
    if (pkg_bridge / "package.json").exists():
        return pkg_bridge
    if (src_bridge / "package.json").exists():
        return src_bridge
    raise WeixinBridgeError("Bridge source not found. Reinstall lemonclaw.")


def get_bridge_dir() -> Path:
    return get_data_dir() / "bridge"


def ensure_bridge_ready() -> Path:
    bridge_dir = get_bridge_dir()
    source = _bridge_source_dir()
    built_entry = bridge_dir / "dist" / "weixin" / "index.js"
    if built_entry.exists():
        built_mtime = built_entry.stat().st_mtime
        source_files = [p for p in source.rglob("*") if p.is_file()]
        if source_files and max(p.stat().st_mtime for p in source_files) <= built_mtime:
            return bridge_dir

    if not shutil.which("npm"):
        raise WeixinBridgeError("npm not found. Please install Node.js >= 20.")

    bridge_dir.parent.mkdir(parents=True, exist_ok=True)
    if bridge_dir.exists():
        shutil.rmtree(bridge_dir)
    shutil.copytree(source, bridge_dir, ignore=shutil.ignore_patterns("node_modules", "dist"))

    try:
        subprocess.run(["npm", "install"], cwd=bridge_dir, check=True, capture_output=True, text=True)
        subprocess.run(["npm", "run", "build"], cwd=bridge_dir, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise WeixinBridgeError(f"Failed to build Weixin bridge: {detail[:400]}") from exc

    return bridge_dir


def _parse_bridge_endpoint(bridge_url: str) -> tuple[str, int]:
    parsed = urlparse(bridge_url)
    if parsed.scheme not in {"http", "https"}:
        raise WeixinBridgeError(f"Unsupported bridge URL scheme: {bridge_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3002
    return host, port


def is_bridge_reachable(bridge_url: str) -> bool:
    host, port = _parse_bridge_endpoint(bridge_url)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def build_bridge_env(config: WeixinConfig) -> dict[str, str]:
    bridge_url = config.bridge_url or "http://127.0.0.1:3002"
    host, port = _parse_bridge_endpoint(bridge_url)
    if host not in {"127.0.0.1", "localhost"}:
        raise WeixinBridgeError("Only local bridge_url values are supported for Weixin pairing.")

    env = {**os.environ}
    env["WEIXIN_BRIDGE_PORT"] = str(port)
    env["WEIXIN_BRIDGE_STATE_FILE"] = str(get_bridge_state_path())
    env["WEIXIN_ACCOUNTS_DIR"] = str(get_weixin_accounts_dir())
    env["WEIXIN_MEDIA_DIR"] = str(get_weixin_media_dir())
    env["WEIXIN_BASE_URL"] = config.base_url or "https://ilinkai.weixin.qq.com"
    env["WEIXIN_CDN_BASE_URL"] = config.cdn_base_url or "https://novac2c.cdn.weixin.qq.com/c2c"
    if config.bridge_token:
        env["WEIXIN_BRIDGE_TOKEN"] = config.bridge_token
    return env


def _bridge_request(
    config: WeixinConfig,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> dict[str, object]:
    bridge_url = config.bridge_url or "http://127.0.0.1:3002"
    base = bridge_url.rstrip("/")
    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if config.bridge_token:
        req.add_header("Authorization", f"Bearer {config.bridge_token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise WeixinBridgeError(f"Bridge request failed: {payload or exc.reason}") from exc
    except Exception as exc:
        raise WeixinBridgeError(f"Bridge request failed: {exc}") from exc


def start_bridge_process(config: WeixinConfig) -> None:
    bridge_dir = ensure_bridge_ready()
    env = build_bridge_env(config)
    state_path = get_bridge_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_state = state_path.with_suffix(".tmp")
    tmp_state.write_text(json.dumps({"status": "starting", "qr": None, "account": None, "updated_at": time.time(), "pid": None}))
    tmp_state.replace(state_path)

    log_path = get_bridge_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")
    subprocess.Popen(
        ["node", "dist/weixin/index.js"],
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
        return {"status": "stopped", "qr": None, "account": None, "accounts": [], "running": False}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"status": "error", "qr": None, "account": None, "accounts": [], "running": False, "error": "Bridge state file is corrupt."}
    if not isinstance(data, dict):
        return {"status": "error", "qr": None, "account": None, "accounts": [], "running": False, "error": "Bridge state file is invalid."}
    return data


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
    return True


def disconnect_weixin(config: WeixinConfig, account_id: str | None = None) -> dict[str, object]:
    if is_bridge_reachable(config.bridge_url):
        return _bridge_request(config, "/disconnect", method="POST", body={"accountId": account_id})
    return {"status": "disconnected", "qr": None, "account": None, "accounts": [], "running": False}


def ensure_weixin_bridge_running(
    config: WeixinConfig,
    *,
    wait_timeout: float = 10.0,
) -> dict[str, object]:
    bridge_url = config.bridge_url or "http://127.0.0.1:3002"
    running = is_bridge_reachable(bridge_url)

    if not running:
        start_bridge_process(config)
        deadline = time.time() + max(wait_timeout, 1.0)
        while time.time() < deadline:
            if is_bridge_reachable(bridge_url):
                running = True
                break
            time.sleep(0.4)

    if not running:
        raise WeixinBridgeError("Weixin bridge did not become reachable in time.")

    return _bridge_request(config, "/state", timeout=wait_timeout)


def poll_weixin_updates(
    config: WeixinConfig,
    *,
    cursor: int = 0,
    limit: int = 50,
    wait_timeout: float = 25.0,
) -> dict[str, object]:
    params = urlencode(
        {
            "cursor": max(0, int(cursor)),
            "limit": max(1, min(int(limit), 200)),
            "waitMs": int(max(wait_timeout, 0.1) * 1000),
        }
    )
    return _bridge_request(config, f"/updates?{params}", timeout=wait_timeout + 5.0)


def send_weixin_text(
    config: WeixinConfig,
    *,
    account_id: str,
    to: str,
    text: str,
    context_token: str | None = None,
    media_paths: list[str] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "accountId": account_id,
        "to": to,
        "text": text,
    }
    if context_token:
        body["contextToken"] = context_token
    if media_paths:
        body["mediaPaths"] = list(media_paths)
    return _bridge_request(config, "/send", method="POST", body=body, timeout=20.0)


def get_weixin_pairing_state(
    config: WeixinConfig,
    *,
    start_if_needed: bool = False,
    force: bool = False,
    wait_timeout: float = 10.0,
) -> dict[str, object]:
    bridge_url = config.bridge_url or "http://127.0.0.1:3002"
    running = is_bridge_reachable(bridge_url)

    if not running and start_if_needed:
        ensure_weixin_bridge_running(config, wait_timeout=wait_timeout)
        running = True

    if not running:
        return {**read_bridge_state(), "running": False}

    if start_if_needed:
        return _bridge_request(config, "/login/start", method="POST", body={"force": force}, timeout=wait_timeout)
    return _bridge_request(config, "/state", timeout=wait_timeout)
