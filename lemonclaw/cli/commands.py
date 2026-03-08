"""CLI commands for lemonclaw."""

import asyncio
import os
import signal
from pathlib import Path
import select
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from lemonclaw import __version__, __logo__
from lemonclaw.config.schema import Config
from lemonclaw.utils.helpers import sync_workspace_templates

app = typer.Typer(
    name="lemonclaw",
    help=f"{__logo__} lemonclaw - AI Agent Platform",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        logger.debug("Terminal state restore failed")


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    history_file = Path.home() / ".lemonclaw" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} lemonclaw[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc



def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} lemonclaw v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """lemonclaw - AI Agent Platform."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def init(
    telegram: bool = typer.Option(False, "--telegram", help="Only run Telegram pairing step"),
):
    """Interactive setup wizard: config, service, watchdog, Telegram."""
    from lemonclaw.cli.init import run_init
    run_init(telegram_only=telegram)


@app.command()
def onboard():
    """Quick config setup (legacy). Use `lemonclaw init` for full setup."""
    from lemonclaw.config.loader import get_config_path, load_config, save_config
    from lemonclaw.config.schema import Config
    from lemonclaw.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    sync_workspace_templates(workspace)

    console.print(f"\n{__logo__} lemonclaw is ready!")
    console.print("\nNext steps:")
    console.print("  1. Full setup: [cyan]lemonclaw init[/cyan]")
    console.print("  2. Quick chat: [cyan]lemonclaw agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? Run: lemonclaw init[/dim]")





def _make_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from lemonclaw.providers.litellm_provider import LiteLLMProvider
    from lemonclaw.providers.openai_codex_provider import OpenAICodexProvider
    from lemonclaw.providers.custom_provider import CustomProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        return OpenAICodexProvider(default_model=model)

    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    from lemonclaw.providers.registry import find_by_name
    spec = find_by_name(provider_name)
    if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and spec.is_oauth):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.lemonclaw/config.json under providers section")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18789, "--port", "-p", help="Gateway HTTP port"),
    bind: str = typer.Option("localhost", "--bind", "-b", help="Bind address (localhost|lan|0.0.0.0)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the lemonclaw gateway."""
    from lemonclaw.config.loader import load_config, get_data_dir
    from lemonclaw.config.logging import setup_logging
    from lemonclaw.config.sync import run_config_sync
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.channels.manager import ChannelManager
    from lemonclaw.session.manager import SessionManager
    from lemonclaw.cron.service import CronService
    from lemonclaw.cron.types import CronJob
    from lemonclaw.heartbeat.service import HeartbeatService
    from lemonclaw.gateway.server import create_app, GatewayServer, GracefulShutdown

    setup_logging()

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    # Resolve bind address
    host = bind
    if bind == "lan":
        host = "0.0.0.0"

    console.print(f"{__logo__} Starting lemonclaw gateway on {host}:{port}...")

    config = load_config()

    # Run config-sync (K8s: applies Orchestrator env vars; self-hosted: validation only)
    sync_report = run_config_sync(config)
    if sync_report.changed:
        console.print(f"[green]✓[/green] {sync_report.summary()}")
    if sync_report.failures:
        console.print(f"[yellow]Warning: {sync_report.summary()}[/yellow]")

    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Create usage tracker with budget config
    from lemonclaw.telemetry.usage import UsageTracker
    usage_tracker = UsageTracker(
        token_budget_per_session=config.agents.defaults.token_budget_per_session,
        cost_budget_per_day=config.agents.defaults.cost_budget_per_day,
        input_cost_per_1k_tokens=config.agents.defaults.input_cost_per_1k_tokens,
        output_cost_per_1k_tokens=config.agents.defaults.output_cost_per_1k_tokens,
    )

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create ActivityBus before AgentLoop and ChannelManager (both need it)
    from lemonclaw.bus.activity import ActivityBus
    activity_bus = ActivityBus()

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        usage_tracker=usage_tracker,
        coding_config=config.tools.coding,
        browser_config=config.tools.browser,
        activity_bus=activity_bus,
        default_timezone=config.agents.defaults.timezone,
        system_prompt=config.agents.defaults.system_prompt,
        disabled_skills=config.agents.defaults.disabled_skills,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent or internal handler."""
        if job.payload.kind == "system_event":
            from lemonclaw.memory.cron import is_memory_event, run_memory_event
            if is_memory_event(job.payload.message):
                return await run_memory_event(job.payload.message, config.workspace_path)
            logger.warning("Unknown system_event: {}", job.payload.message)
            return None

        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from lemonclaw.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    cron.on_job = on_cron_job

    # Register memory cron jobs (idempotent)
    from lemonclaw.memory.cron import register_memory_jobs
    register_memory_jobs(cron)

    # Create channel manager
    channels = ChannelManager(config, bus, activity_bus=activity_bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from lemonclaw.bus.events import OutboundMessage
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    # Create in-process watchdog (Layer 1: asyncio health checks)
    from lemonclaw.watchdog.service import WatchdogService, create_loguru_error_sink
    from loguru import logger as _logger

    watchdog = WatchdogService(
        port=port,
        session_manager=session_manager,
    )
    # Feed error log events to watchdog for rate tracking
    _logger.add(create_loguru_error_sink(watchdog), level="ERROR")

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")
    console.print(f"[green]✓[/green] Watchdog: in-process health monitor")

    # Create config watcher (started later in run())
    from lemonclaw.config.watcher import ConfigWatcher
    from lemonclaw.config.loader import get_config_path
    config_watcher = ConfigWatcher(get_config_path(), provider, agent_loop=agent)

    # Build HTTP server
    from lemonclaw import __version__
    asgi_app = create_app(
        auth_token=config.gateway.auth_token,
        channel_manager=channels,
        version=__version__,
        model=config.agents.defaults.model,
        instance_id=getattr(config.lemondata, "instance_id", ""),
        usage_tracker=usage_tracker,
        session_manager=session_manager,
        agent_loop=agent,
        webui_enabled=config.gateway.webui_enabled,
        activity_bus=activity_bus,
        config_path=get_config_path(),
        config_watcher=config_watcher,
    )
    http_server = GatewayServer(asgi_app, host=host, port=port)
    webui_status = "enabled" if config.gateway.webui_enabled else "disabled"
    console.print(f"[green]✓[/green] HTTP server: {host}:{port} (WebUI {webui_status})")

    async def run():
        shutdown = GracefulShutdown()
        shutdown.register_signals()

        await cron.start()
        await heartbeat.start()
        await watchdog.start()

        # Start config file watcher for API key + agent defaults hot-reload
        config_watcher.start()

        # Start incremental memory backup
        from lemonclaw.watchdog.memory_backup import MemoryBackup
        mem_backup = MemoryBackup(config.workspace_path)
        await mem_backup.start()

        # Run agent, channels, HTTP server, and shutdown watcher concurrently
        async def _shutdown_watcher():
            await shutdown.wait()
            watchdog.stop()
            mem_backup.stop()
            config_watcher.stop()
            await shutdown.execute(
                channels=channels,
                agent=agent,
                cron=cron,
                heartbeat=heartbeat,
                http_server=http_server,
            )

        try:
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
                http_server.serve(),
                _shutdown_watcher(),
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show lemonclaw runtime logs during chat"),
):
    """Interact with the agent directly."""
    from lemonclaw.config.loader import load_config, get_data_dir
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.cron.service import CronService
    from loguru import logger
    
    config = load_config()
    sync_workspace_templates(config.workspace_path)
    
    bus = MessageBus()
    provider = _make_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("lemonclaw")
    else:
        logger.disable("lemonclaw")
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        coding_config=config.tools.coding,
        browser_config=config.tools.browser,
        default_timezone=config.agents.defaults.timezone,
        system_prompt=config.agents.defaults.system_prompt,
        disabled_skills=config.agents.defaults.disabled_skills,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]lemonclaw is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from lemonclaw.bus.events import InboundMessage
        _init_prompt_session()
        console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from lemonclaw.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "Feishu",
        "✓" if fs.enabled else "✗",
        fs_config
    )

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row(
        "Mochat",
        "✓" if mc.enabled else "✗",
        mc_base
    )
    
    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row(
        "Slack",
        "✓" if slack.enabled else "✗",
        slack_config
    )

    # DingTalk
    dt = config.channels.dingtalk
    dt_config = f"client_id: {dt.client_id[:10]}..." if dt.client_id else "[dim]not configured[/dim]"
    table.add_row(
        "DingTalk",
        "✓" if dt.enabled else "✗",
        dt_config
    )

    # QQ
    qq = config.channels.qq
    qq_config = f"app_id: {qq.app_id[:10]}..." if qq.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "QQ",
        "✓" if qq.enabled else "✗",
        qq_config
    )

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]not configured[/dim]"
    table.add_row(
        "Email",
        "✓" if em.enabled else "✗",
        em_config
    )

    # Matrix
    matrix = config.channels.matrix
    matrix_config = matrix.user_id or matrix.homeserver or "[dim]not configured[/dim]"
    table.add_row(
        "Matrix",
        "✓" if matrix.enabled else "✗",
        matrix_config
    )

    # WeCom
    wecom = config.channels.wecom
    wecom_config = wecom.corp_id or "[dim]not configured[/dim]"
    table.add_row(
        "WeCom",
        "✓" if wecom.enabled else "✗",
        wecom_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    from lemonclaw.channels.whatsapp_bridge_runtime import WhatsAppBridgeError, ensure_bridge_ready

    console.print(f"{__logo__} Setting up bridge...")
    try:
        bridge_dir = ensure_bridge_ready()
    except WhatsAppBridgeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print("[green]✓[/green] Bridge ready\n")
    return bridge_dir


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    from lemonclaw.config.loader import load_config
    
    config = load_config()
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    env = {**os.environ}
    env["AUTH_DIR"] = str((Path.home() / '.lemonclaw' / 'whatsapp-auth'))
    env["BRIDGE_STATE_FILE"] = str((Path.home() / '.lemonclaw' / 'whatsapp-bridge-state.json'))
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from lemonclaw.config.loader import get_data_dir
    from lemonclaw.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = f"{job.schedule.expr or ''} ({job.schedule.tz})" if job.schedule.tz else (job.schedule.expr or "")
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            ts = job.state.next_run_at_ms / 1000
            try:
                tz = ZoneInfo(job.schedule.tz) if job.schedule.tz else None
                next_run = _dt.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")
            except Exception:
                next_run = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    tz: str | None = typer.Option(None, "--tz", help="IANA timezone for cron (e.g. 'America/Vancouver')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from lemonclaw.config.loader import get_data_dir
    from lemonclaw.cron.service import CronService
    from lemonclaw.cron.types import CronSchedule
    
    if tz and not cron_expr:
        console.print("[red]Error: --tz can only be used with --cron[/red]")
        raise typer.Exit(1)

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    try:
        job = service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            to=to,
            channel=channel,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from lemonclaw.config.loader import get_data_dir
    from lemonclaw.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from lemonclaw.config.loader import get_data_dir
    from lemonclaw.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from loguru import logger
    from lemonclaw.config.loader import load_config, get_data_dir
    from lemonclaw.cron.service import CronService
    from lemonclaw.cron.types import CronJob
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.agent.loop import AgentLoop
    logger.disable("lemonclaw")

    config = load_config()
    provider = _make_provider(config)
    bus = MessageBus()
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        coding_config=config.tools.coding,
        browser_config=config.tools.browser,
        default_timezone=config.agents.defaults.timezone,
        system_prompt=config.agents.defaults.system_prompt,
        disabled_skills=config.agents.defaults.disabled_skills,
    )

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    result_holder = []

    async def on_job(job: CronJob) -> str | None:
        response = await agent_loop.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        result_holder.append(response)
        return response

    service.on_job = on_job

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print("[green]✓[/green] Job executed")
        if result_holder:
            _print_agent_response(result_holder[0], render_markdown=True)
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show lemonclaw status."""
    from lemonclaw.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} lemonclaw Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from lemonclaw.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# ============================================================================
# Doctor (pre-flight diagnostics)
# ============================================================================


@app.command()
def doctor(
    fix: bool = typer.Option(False, "--fix", "-f", help="Auto-fix issues where possible"),
):
    """Pre-flight diagnostics: check config, API key, port, workspace, versions."""
    import socket
    from lemonclaw.config.loader import get_config_path, load_config
    from lemonclaw.config.defaults import DEFAULT_GATEWAY_PORT

    console.print(f"{__logo__} lemonclaw doctor\n")

    issues: list[str] = []
    fixed: list[str] = []

    # 1. Config file exists
    config_path = get_config_path()
    if config_path.exists():
        console.print(f"  [green]✓[/green] Config: {config_path}")
        config = load_config()
    else:
        console.print(f"  [red]✗[/red] Config: {config_path} not found")
        if fix:
            from lemonclaw.config.schema import Config
            from lemonclaw.config.loader import save_config
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = Config()
            save_config(config)
            console.print(f"    [cyan]→ Created default config[/cyan]")
            fixed.append("config")
        else:
            issues.append("config missing (run with --fix or `lemonclaw init`)")
            config = None

    # 2. API key configured
    if config:
        ld = config.providers.lemondata
        if ld.api_key and ld.api_key.startswith("sk-"):
            masked = f"{ld.api_key[:12]}...{ld.api_key[-4:]}"
            console.print(f"  [green]✓[/green] API key: {masked}")
        else:
            console.print(f"  [red]✗[/red] API key: not configured")
            issues.append("API key missing (run `lemonclaw init`)")

    # 3. Workspace exists
    if config:
        ws = config.workspace_path
        if ws.exists():
            console.print(f"  [green]✓[/green] Workspace: {ws}")
        else:
            console.print(f"  [red]✗[/red] Workspace: {ws} not found")
            if fix:
                ws.mkdir(parents=True, exist_ok=True)
                sync_workspace_templates(ws)
                console.print(f"    [cyan]→ Created workspace[/cyan]")
                fixed.append("workspace")
            else:
                issues.append("workspace missing (run with --fix)")

    # 4. Required subdirectories
    if config:
        config_dir = config_path.parent
        for subdir in ("sessions", "memory", "credentials"):
            d = config_dir / subdir
            if d.exists():
                console.print(f"  [green]✓[/green] Dir: {subdir}/")
            else:
                console.print(f"  [red]✗[/red] Dir: {subdir}/ missing")
                if fix:
                    d.mkdir(parents=True, exist_ok=True)
                    console.print(f"    [cyan]→ Created {subdir}/[/cyan]")
                    fixed.append(subdir)
                else:
                    issues.append(f"{subdir}/ missing (run with --fix)")

    # 5. Port available
    port = DEFAULT_GATEWAY_PORT
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            if result == 0:
                console.print(f"  [yellow]![/yellow] Port {port}: in use (gateway may be running)")
            else:
                console.print(f"  [green]✓[/green] Port {port}: available")
    except Exception:
        console.print(f"  [green]✓[/green] Port {port}: available")

    # 6. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    console.print(f"  {'[green]✓[/green]' if py_ok else '[red]✗[/red]'} Python: {py_ver}")
    if not py_ok:
        issues.append("Python >= 3.11 required")

    # 7. Node.js (optional)
    import shutil
    if shutil.which("node"):
        try:
            import subprocess
            result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
            node_ver = result.stdout.strip().lstrip("v")
            console.print(f"  [green]✓[/green] Node.js: {node_ver}")
        except Exception:
            console.print(f"  [yellow]![/yellow] Node.js: found but version check failed")
    else:
        console.print(f"  [dim]-[/dim] Node.js: not found (optional, for WhatsApp bridge)")

    # Summary
    console.print()
    if fixed:
        console.print(f"  [cyan]Fixed {len(fixed)} issue(s): {', '.join(fixed)}[/cyan]")
    if issues:
        console.print(f"  [red]{len(issues)} issue(s) found:[/red]")
        for issue in issues:
            console.print(f"    • {issue}")
        raise typer.Exit(1)
    else:
        console.print(f"  [green]All checks passed.[/green]")


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn
    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Authenticate with an OAuth provider."""
    from lemonclaw.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive
        token = None
        try:
            token = get_token()
        except Exception:
            logger.debug("Cached token retrieval failed, will prompt login")
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger():
        from litellm import acompletion
        await acompletion(model="github_copilot/gpt-4o", messages=[{"role": "user", "content": "hi"}], max_tokens=1)

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
