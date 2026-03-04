"""lemonclaw init - Interactive setup wizard.

Replaces the curl|bash pattern with a safe, built-in installer.
Generates config, registers system service (launchd/systemd), watchdog,
and optionally pairs Telegram.

Usage:
    pip install lemonclaw
    lemonclaw init
"""

import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lemonclaw import __version__
from lemonclaw.config.defaults import (
    DEFAULT_GATEWAY_PORT,
    DEFAULT_MODEL,
    LEMONDATA_API_BASE,
    LEMONDATA_API_BASE_V1,
    PROVIDER_LEMONDATA,
    PROVIDER_LEMONDATA_CLAUDE,
    PROVIDER_LEMONDATA_MINIMAX,
)

console = Console()

CONFIG_DIR = Path.home() / ".lemonclaw"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Service identifiers
LAUNCHD_LABEL = "cc.lemondata.lemonclaw"
LAUNCHD_WATCHDOG_LABEL = "cc.lemondata.lemonclaw-watchdog"
SYSTEMD_SERVICE = "lemonclaw.service"
SYSTEMD_WATCHDOG_SERVICE = "lemonclaw-watchdog.service"
SYSTEMD_WATCHDOG_TIMER = "lemonclaw-watchdog.timer"


# ============================================================================
# Main entry point
# ============================================================================


def run_init(*, telegram_only: bool = False) -> None:
    """Run the full interactive init wizard."""
    console.print(Panel.fit(
        f"[bold cyan]🐾 LemonClaw v{__version__} — Setup Wizard[/bold cyan]\n"
        "[dim]Configure LemonClaw for self-hosted deployment.[/dim]",
        border_style="cyan",
    ))
    console.print()

    if telegram_only:
        _step_telegram_pairing()
        return

    # Step 1: OS detection
    if not _step_detect_os():
        raise typer.Exit(1)

    # Step 2: Python version check
    if not _step_check_python():
        raise typer.Exit(1)

    # Step 3: Node.js detection (optional)
    _step_check_node()

    # Step 4: API key input
    api_key = _step_api_key_input()

    # Step 5: Generate config
    gateway_token = _step_generate_config(api_key)

    # Step 6: Create subdirectories
    _step_create_subdirectories()

    # Step 7: Register system service
    service_registered = _step_register_service()

    # Step 8: Generate watchdog
    if service_registered:
        _step_generate_watchdog()

    # Step 9: Start service
    if service_registered:
        _step_start_service()

    # Step 10: Telegram pairing (optional)
    _step_telegram_pairing()

    # Summary
    _print_summary(gateway_token, service_registered)


# ============================================================================
# Step 1: OS detection
# ============================================================================


def _step_detect_os() -> bool:
    """Detect OS and architecture."""
    console.print("[bold]Step 1/10: OS Detection[/bold]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Check", style="dim")
    table.add_column("Value")
    table.add_column("Status")

    os_name = platform.system()
    os_ver = platform.release()
    os_ok = os_name in ("Darwin", "Linux")
    table.add_row("OS", f"{os_name} {os_ver}", _check(os_ok))

    arch = platform.machine()
    table.add_row("Arch", arch, _check(True))

    lc_path = shutil.which("lemonclaw")
    table.add_row("Binary", lc_path or "running from source", _check(True))

    console.print(table)
    console.print()

    if not os_ok:
        console.print("[red]Unsupported OS. LemonClaw requires macOS or Linux.[/red]")
        return False
    return True


# ============================================================================
# Step 2: Python version check
# ============================================================================


def _step_check_python() -> bool:
    """Verify Python >= 3.11."""
    console.print("[bold]Step 2/10: Python Version[/bold]\n")

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    console.print(f"  Python: {py_ver} {_check(py_ok, fail='>=3.11 required')}")
    console.print()

    if not py_ok:
        console.print("[red]Python >=3.11 required. Please upgrade.[/red]")
        return False
    return True


# ============================================================================
# Step 3: Node.js detection (optional)
# ============================================================================


def _step_check_node() -> None:
    """Check Node.js availability (optional, for WhatsApp bridge)."""
    console.print("[bold]Step 3/10: Node.js (optional)[/bold]\n")

    node_ver = _get_node_version()
    if node_ver:
        node_major = int(node_ver.split(".")[0])
        node_ok = node_major >= 20
        console.print(f"  Node.js: {node_ver} {_check(node_ok, fail='>=20 for WhatsApp')}")
    else:
        console.print("  Node.js: not found [yellow](optional)[/yellow] — needed for WhatsApp bridge")
    console.print()


# ============================================================================
# Step 4: API key input
# ============================================================================


def _step_api_key_input() -> str:
    """Get API key from existing config, env var, or interactive input."""
    console.print("[bold]Step 4/10: API Key[/bold]\n")

    # Check existing config
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Try both camelCase and snake_case keys
            providers = existing.get("providers", {})
            ld = providers.get(PROVIDER_LEMONDATA) or providers.get("lemondata", {})
            existing_key = ld.get("api_key") or ld.get("apiKey", "")
            if existing_key and existing_key.startswith("sk-"):
                masked = f"{existing_key[:12]}...{existing_key[-4:]}"
                console.print(f"  Found existing key: [cyan]{masked}[/cyan]")
                if typer.confirm("  Use existing key?", default=True):
                    console.print()
                    return existing_key
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Check env var
    env_key = os.environ.get("API_KEY", "")
    if env_key and env_key.startswith("sk-"):
        masked = f"{env_key[:12]}...{env_key[-4:]}"
        console.print(f"  Found API_KEY in environment: [cyan]{masked}[/cyan]")
        if typer.confirm("  Use this key?", default=True):
            console.print()
            return env_key

    # Interactive input
    console.print("  Get your API key at: [link=https://lemondata.cc/dashboard/api-keys]https://lemondata.cc/dashboard/api-keys[/link]")
    while True:
        api_key = typer.prompt("  API key (sk-...)")
        if api_key.startswith("sk-") and len(api_key) > 10:
            console.print()
            return api_key
        console.print("  [red]Invalid format. Must start with sk- and be >10 chars.[/red]")


# ============================================================================
# Step 5: Generate configuration
# ============================================================================


def _step_generate_config(api_key: str) -> str:
    """Generate ~/.lemonclaw/config.json via Pydantic for format safety."""
    from lemonclaw.config.loader import load_config, save_config

    console.print("[bold]Step 5/10: Generate Configuration[/bold]\n")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing config (preserves channels, tools, etc.) or create new
    config = load_config()

    # Set LemonData providers (SSOT from defaults.py)
    config.providers.lemondata.api_key = api_key
    config.providers.lemondata.api_base = LEMONDATA_API_BASE_V1

    config.providers.lemondata_claude.api_key = api_key
    config.providers.lemondata_claude.api_base = LEMONDATA_API_BASE  # No /v1 for Anthropic

    config.providers.lemondata_minimax.api_key = api_key
    config.providers.lemondata_minimax.api_base = LEMONDATA_API_BASE  # No /v1 — MiniMax native = Anthropic format

    # Set default model from SSOT
    config.agents.defaults.model = DEFAULT_MODEL

    # Generate gateway auth token if not already set
    gateway_token = config.gateway.auth_token or secrets.token_hex(32)
    config.gateway.auth_token = gateway_token

    # LemonData platform config
    config.lemondata.api_base_url = LEMONDATA_API_BASE
    config.lemondata.api_key = api_key

    # Save via Pydantic → guaranteed camelCase format
    save_config(config)

    # Restrict permissions (config contains API key)
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass

    console.print(f"  [green]✓[/green] Config: {CONFIG_FILE}")
    console.print(f"  [green]✓[/green] Gateway token: {gateway_token[:12]}...")
    console.print(f"  [green]✓[/green] Model: {DEFAULT_MODEL}")
    console.print(f"  [green]✓[/green] Providers: {PROVIDER_LEMONDATA}, {PROVIDER_LEMONDATA_CLAUDE}, {PROVIDER_LEMONDATA_MINIMAX}")
    console.print()

    return gateway_token


# ============================================================================
# Step 6: Create subdirectories
# ============================================================================


def _step_create_subdirectories() -> None:
    """Create required subdirectories under ~/.lemonclaw/."""
    console.print("[bold]Step 6/10: Create Subdirectories[/bold]\n")

    for subdir in ("sessions", "memory", "credentials", "workspace"):
        d = CONFIG_DIR / subdir
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]✓[/green] {d}")
    console.print()


# ============================================================================
# Step 7: Register system service
# ============================================================================


def _step_register_service() -> bool:
    """Register launchd (macOS) or systemd (Linux) service."""
    console.print("[bold]Step 7/10: System Service[/bold]\n")

    system = platform.system()
    if system == "Darwin":
        return _register_launchd()
    elif system == "Linux":
        return _register_systemd()
    else:
        console.print("  [yellow]Skipped: unsupported OS for service registration[/yellow]\n")
        return False


# ============================================================================
# Step 8: Watchdog
# ============================================================================


def _step_generate_watchdog() -> None:
    """Generate external watchdog (launchd plist / systemd timer)."""
    console.print("[bold]Step 8/10: Watchdog[/bold]\n")

    system = platform.system()
    if system == "Darwin":
        _generate_launchd_watchdog()
    elif system == "Linux":
        _generate_systemd_watchdog()


# ============================================================================
# Step 9: Start service
# ============================================================================


def _step_start_service() -> None:
    """Start the registered service."""
    console.print("[bold]Step 9/10: Start Service[/bold]\n")

    if not typer.confirm("  Start LemonClaw now?", default=True):
        console.print("  [dim]Skipped. Start manually later.[/dim]\n")
        return

    system = platform.system()
    try:
        if system == "Darwin":
            plist = _launchd_plist_path()
            # Unload first (idempotent, ignore errors)
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
                capture_output=True,
            )
            subprocess.run(
                ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                check=True, capture_output=True,
            )
            console.print("  [green]✓[/green] Service started (launchd)")
        elif system == "Linux":
            subprocess.run(
                ["systemctl", "--user", "start", SYSTEMD_SERVICE],
                check=True, capture_output=True,
            )
            console.print("  [green]✓[/green] Service started (systemd)")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ""
        console.print(f"  [red]Failed to start: {stderr or e}[/red]")
        console.print(f"  [dim]Start manually: lemonclaw gateway --bind lan --port {DEFAULT_GATEWAY_PORT}[/dim]")

    console.print()


# ============================================================================
# Step 10: Telegram pairing
# ============================================================================


def _step_telegram_pairing() -> None:
    """Interactive Telegram bot pairing guide."""
    console.print("[bold]Step 10/10: Telegram Pairing (optional)[/bold]\n")

    if not typer.confirm("  Set up Telegram bot?", default=False):
        console.print("  [dim]Skipped. Run `lemonclaw init --telegram` later.[/dim]\n")
        return

    console.print()
    console.print("  [bold]Follow these steps:[/bold]")
    console.print("  1. Open Telegram -> search @BotFather")
    console.print("  2. Send /newbot -> choose a name and username")
    console.print("  3. Copy the bot token (e.g. 123456:ABC-DEF...)")
    console.print()

    token = typer.prompt("  Telegram bot token")
    if not token or ":" not in token:
        console.print("  [red]Invalid token. Expected format: 123456:ABC-DEF...[/red]\n")
        return

    # Update config with Telegram channel
    from lemonclaw.config.loader import load_config, save_config

    config = load_config()
    config.channels.telegram.enabled = True
    config.channels.telegram.token = token
    save_config(config)

    console.print("  [green]✓[/green] Telegram configured")
    console.print()

    # Restart hint
    system = platform.system()
    if system == "Darwin":
        console.print(f"  Restart: launchctl kickstart -k gui/{os.getuid()}/{LAUNCHD_LABEL}")
    elif system == "Linux":
        console.print(f"  Restart: systemctl --user restart {SYSTEMD_SERVICE}")

    console.print("  Then send a message to your bot — LemonClaw will auto-pair.")
    console.print()


# ============================================================================
# Summary
# ============================================================================


def _print_summary(gateway_token: str, service_registered: bool) -> None:
    """Print final setup summary."""
    manual_cmd = f"lemonclaw gateway --bind lan --port {DEFAULT_GATEWAY_PORT}"
    service_line = (
        "\n[dim]Service registered and running.[/dim]"
        if service_registered
        else f"\n[dim]Run manually: {manual_cmd}[/dim]"
    )

    console.print(Panel.fit(
        f"[bold green]🐾 LemonClaw Setup Complete![/bold green]\n\n"
        f"Config:   {CONFIG_FILE}\n"
        f"Model:    {DEFAULT_MODEL}\n"
        f"Gateway:  http://localhost:{DEFAULT_GATEWAY_PORT}\n"
        f"Token:    {gateway_token[:12]}..."
        + service_line,
        border_style="green",
    ))
    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  Health check:  curl http://localhost:{DEFAULT_GATEWAY_PORT}/health")
    console.print(f"  View logs:     tail -f {CONFIG_DIR}/lemonclaw.log")
    console.print(f"  Status:        lemonclaw status")
    console.print()


# ============================================================================
# Helpers
# ============================================================================


def _check(ok: bool, *, fail: str = "") -> str:
    """Format a status indicator."""
    if ok:
        return "[green]✓[/green]"
    return f"[red]✗ {fail}[/red]" if fail else "[red]✗[/red]"


def _get_node_version() -> str | None:
    """Get installed Node.js version or None."""
    try:
        result = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().lstrip("v")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ============================================================================
# macOS launchd
# ============================================================================


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_watchdog_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_WATCHDOG_LABEL}.plist"


def _find_lemonclaw_bin() -> str:
    """Find the lemonclaw binary path."""
    found = shutil.which("lemonclaw")
    if found:
        return found
    # Fallback: derive from current Python executable
    py_dir = Path(sys.executable).parent
    candidate = py_dir / "lemonclaw"
    if candidate.exists():
        return str(candidate)
    return "lemonclaw"  # Hope it's on PATH at runtime


def _register_launchd() -> bool:
    """Create and register macOS LaunchAgent plist."""
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    lc_bin = _find_lemonclaw_bin()
    home = str(Path.home())

    # Build PATH: include homebrew (Apple Silicon + Intel) and standard paths
    path_dirs = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    # Also include the directory containing lemonclaw
    bin_dir = str(Path(lc_bin).parent)
    if bin_dir not in path_dirs:
        path_dirs = f"{bin_dir}:{path_dirs}"

    plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{lc_bin}</string>
        <string>gateway</string>
        <string>--bind</string>
        <string>lan</string>
        <string>--port</string>
        <string>{DEFAULT_GATEWAY_PORT}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{CONFIG_DIR}/lemonclaw.log</string>
    <key>StandardErrorPath</key>
    <string>{CONFIG_DIR}/lemonclaw.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{home}</string>
        <key>PATH</key>
        <string>{path_dirs}</string>
    </dict>
</dict>
</plist>
"""

    plist_path.write_text(plist_content)
    console.print(f"  [green]✓[/green] Created: {plist_path}")
    return True


def _generate_launchd_watchdog() -> None:
    """Create watchdog script and launchd plist (every 300s)."""
    watchdog_path = _launchd_watchdog_path()
    watchdog_script = CONFIG_DIR / "watchdog.sh"

    watchdog_script.write_text(f"""\
#!/bin/bash
# LemonClaw Watchdog — checks /health endpoint
HEALTH_URL="http://localhost:{DEFAULT_GATEWAY_PORT}/health"
if ! curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
    echo "$(date): Health check failed, restarting..." >> "{CONFIG_DIR}/watchdog.log"
    launchctl kickstart -k "gui/$(id -u)/{LAUNCHD_LABEL}"
fi
""")
    watchdog_script.chmod(0o755)

    plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_WATCHDOG_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{watchdog_script}</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>StandardOutPath</key>
    <string>{CONFIG_DIR}/watchdog.log</string>
    <key>StandardErrorPath</key>
    <string>{CONFIG_DIR}/watchdog.log</string>
</dict>
</plist>
"""

    watchdog_path.write_text(plist_content)
    console.print(f"  [green]✓[/green] Watchdog: {watchdog_script}")
    console.print(f"  [green]✓[/green] Plist: {watchdog_path}")
    console.print("  [dim]Interval: every 300s (5 min)[/dim]")
    console.print()


# ============================================================================
# Linux systemd
# ============================================================================


def _systemd_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _register_systemd() -> bool:
    """Create and enable user-level systemd service."""
    unit_dir = _systemd_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)

    lc_bin = _find_lemonclaw_bin()
    home = str(Path.home())

    service_content = f"""\
[Unit]
Description=LemonClaw AI Agent Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
ExecStart={lc_bin} gateway --bind lan --port {DEFAULT_GATEWAY_PORT}
Restart=on-failure
RestartSec=5
Environment=HOME={home}

[Install]
WantedBy=default.target
"""

    service_path = unit_dir / SYSTEMD_SERVICE
    service_path.write_text(service_content)

    # Reload and enable
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", SYSTEMD_SERVICE],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"  [yellow]Warning: systemctl enable failed: {e}[/yellow]")

    console.print(f"  [green]✓[/green] Created: {service_path}")
    return True


def _generate_systemd_watchdog() -> None:
    """Create systemd watchdog service + timer (every 300s)."""
    unit_dir = _systemd_dir()

    watchdog_service = f"""\
[Unit]
Description=LemonClaw Health Watchdog

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -sf http://localhost:{DEFAULT_GATEWAY_PORT}/health > /dev/null 2>&1 || systemctl --user restart {SYSTEMD_SERVICE}'
"""

    watchdog_timer = """\
[Unit]
Description=LemonClaw Health Check Timer

[Timer]
OnBootSec=60
OnUnitActiveSec=300

[Install]
WantedBy=timers.target
"""

    (unit_dir / SYSTEMD_WATCHDOG_SERVICE).write_text(watchdog_service)
    (unit_dir / SYSTEMD_WATCHDOG_TIMER).write_text(watchdog_timer)

    # Enable timer
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", SYSTEMD_WATCHDOG_TIMER],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass

    console.print(f"  [green]✓[/green] Watchdog: {unit_dir / SYSTEMD_WATCHDOG_SERVICE}")
    console.print(f"  [green]✓[/green] Timer: {unit_dir / SYSTEMD_WATCHDOG_TIMER}")
    console.print("  [dim]Interval: every 300s (5 min)[/dim]")
    console.print()
