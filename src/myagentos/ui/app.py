"""Mya — Interactive terminal application for Agentic OS.

This is the main entry point for the `mya` command.
Built on Textual. The UI is a derived view of the Event Store.
The UI contains no security logic and sends commands to the Job Controller.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Input, OptionList, Static
from textual.worker import Worker

from myagentos.gateway.client import ModelGateway
from myagentos.mya.agent import MyaAgent
from myagentos.mya.commands import (
    CommandHandlerService,
    ObservabilityService,
    format_command_badge,
)
from myagentos.mya.presentation import MyaRenderState, get_mya_renderer
from myagentos.ui.commands import (
    COMMAND_CATALOG,
    ParsedCommand,
    SlashCommandKind,
    get_command_info,
    parse_input,
)
from myagentos.ui.screens.projects import ProjectsScreen
from myagentos.ui.session import create_session
from myagentos.ui.theme.mya_theme import (
    MUTED,
    MYA_RICH_THEME,
    PROVIDERS,
    SAGE,
    SAND,
    StatusLine,
    Thinking,
    Welcome,
    register_all_themes,
    resolve_provider,
)
from myagentos.ui.theme.textual_themes import MYA_TEXTUAL_THEMES, PRESENTATION_TO_TEXTUAL
from myagentos.ui.theme.themes import ThemeRegistry
from myagentos.ui.themes import COST_COLORS, Colors, Icons
from myagentos.ui.visual.motion import MotionController
from myagentos.ui.widgets.chat import (
    ChatMessage,
    CommandSuggestions,
    MessageRole,
    PromptInput,
    ThinkingIndicator,
    WelcomePanel,
)

T = TypeVar("T")

PROMPT_HINTS = "Enter enviar · / comandos · Tab completar · ↑↓ historial"


def _copy_to_macos_clipboard(text: str) -> None:
    subprocess.run(
        ["pbcopy"],
        input=text,
        text=True,
        check=True,
        timeout=2,
    )


def build_help() -> RenderableType:
    """Render the command reference as a grouped, aligned table."""
    intro = Text.from_markup("Describe lo que quieres construir — o usa uno de estos comandos:\n")
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, style=Colors.MUTED)
    table.add_column()
    table.add_column(no_wrap=True)

    current_category = ""
    for info in COMMAND_CATALOG:
        if info.category != current_category:
            if current_category:
                table.add_row("", "", "", "")
            table.add_row(Text(info.category.upper(), style=f"bold {Colors.ACCENT}"), "", "", "")
            current_category = info.category
        cost = Text("●", style=COST_COLORS[info.cost]) if info.cost else Text("")
        table.add_row(
            Text(info.name, style=f"bold {Colors.PRIMARY}"), info.args, info.description, cost
        )

    legend = Text.assemble(
        "\nCoste:  ",
        ("●", COST_COLORS["low"]),
        " bajo   ",
        ("●", COST_COLORS["medium"]),
        " medio   ",
        ("●", COST_COLORS["high"]),
        " alto   ",
        ("●", COST_COLORS["max"]),
        " máximo",
        style=Colors.MUTED,
    )
    return Group(intro, table, legend)


class MyaApp(App[None]):
    """Mya — Agentic OS interactive terminal interface.

    Mya is the voice of the operating system.
    Competent, calm, slightly ironic, and always useful.
    """

    TITLE = "Mya · Agentic OS"
    COMMAND_PALETTE_BINDING = "ctrl+k"
    CSS_PATH = "mya.tcss"
    provider = reactive("mya")

    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancelar", show=False, priority=True),
        Binding("ctrl+d", "quit", "Salir", show=True, priority=True),
        Binding("ctrl+p", "open_projects", "Proyectos", show=True),
        Binding("ctrl+l", "clear_conversation", "Limpiar", show=True),
        Binding("f1", "show_commands", "Comandos", show=True),
        Binding("f2", "next_model", "Modelo", show=True),
        Binding("escape", "escape", "Escape", show=False),
    ]

    @staticmethod
    def _load_env(repo_path: Path | None = None) -> None:
        """Loads key=value pairs from .env into os.environ if not already set."""
        search_paths: list[Path] = []
        if repo_path:
            search_paths.append(repo_path / ".env")
        else:
            search_paths.extend([Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"])
        for env_path in search_paths:
            if env_path.is_file():
                try:
                    with env_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
                except Exception:
                    pass
                break

    @staticmethod
    def _create_default_gateway(
        requested_model: str | None = None,
    ) -> tuple[ModelGateway, str]:
        """Create ModelGateway with available provider adapters and determine active model."""
        gateway = ModelGateway()
        from myagentos.gateway.mock_adapter import MockProviderAdapter

        gateway.register_adapter("mock", MockProviderAdapter())

        has_openai = bool(os.getenv("OPENAI_API_KEY"))
        has_gemini = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))

        if has_openai:
            try:
                from myagentos.gateway.openai_adapter import OpenAIAdapter

                gateway.register_adapter("openai", OpenAIAdapter())
            except Exception:
                pass

        if has_gemini:
            try:
                from myagentos.gateway.gemini_adapter import GeminiAdapter

                gateway.register_adapter("google", GeminiAdapter())
            except Exception:
                pass

        if has_anthropic:
            try:
                from myagentos.gateway.claude_adapter import ClaudeAdapter

                gateway.register_adapter("anthropic", ClaudeAdapter())
            except Exception:
                pass

        default_model = "mock-mya"
        if requested_model:
            default_model = requested_model
        elif has_anthropic:
            default_model = "claude-3-5-sonnet-latest"
        elif has_openai:
            default_model = "gpt-4o"
        elif has_gemini:
            default_model = "gemini-2.0-flash"

        return gateway, default_model

    def __init__(
        self,
        repo_path: Path | None = None,
        gateway: ModelGateway | None = None,
        model_id: str | None = None,
        check_first_run: bool | None = None,
    ) -> None:
        super().__init__()
        self.session = create_session(repo_path)
        self._load_env(repo_path)

        resolved_model = model_id or os.getenv("MYA_MODEL")
        if gateway is not None:
            self.gateway = gateway
            actual_model = resolved_model or "mock-mya"
        else:
            self.gateway, default_model = self._create_default_gateway(resolved_model)
            actual_model = resolved_model or default_model

        if "mock" not in self.gateway.adapters:
            from myagentos.gateway.mock_adapter import MockProviderAdapter

            self.gateway.register_adapter("mock", MockProviderAdapter())

        self.mya_agent = MyaAgent(gateway=self.gateway, model_id=actual_model)
        self._history: list[str] = []
        self._conversation_history: list[dict[str, str]] = []
        self._history_index: int = -1
        self._history_draft: str = ""
        self._suppress_suggestions: bool = False
        self._active_worker: Worker[None] | None = None
        self._user_display_name: str = ""
        from myagentos.config.loader import load_config
        from myagentos.config.paths import DEFAULT_MYA_HOME

        self._mya_home: Path = DEFAULT_MYA_HOME
        saved_cfg = load_config()
        if saved_cfg and saved_cfg.user and saved_cfg.user.display_name:
            self._user_display_name = saved_cfg.user.display_name
        else:
            import getpass

            try:
                self._user_display_name = getpass.getuser().capitalize()
            except Exception:
                self._user_display_name = "Andmo"
        if check_first_run is not None:
            self.check_first_run: bool = check_first_run
        else:
            self.check_first_run = (
                "PYTEST_CURRENT_TEST" not in os.environ
                and os.environ.get("MYA_SKIP_FIRST_RUN") != "1"
            )

        register_all_themes(self)
        for textual_theme in MYA_TEXTUAL_THEMES:
            try:
                self.register_theme(textual_theme)
            except Exception:
                pass
        self.console.push_theme(MYA_RICH_THEME)

        self.model_id = actual_model
        self.provider = resolve_provider(actual_model)
        self.theme = f"mya-{self.provider}"

    def set_model(
        self,
        model_id: str,
        provider: str | None = None,
        notify_chat: bool = False,
    ) -> None:
        """Punto de entrada único para cambiar de modelo (arranque, /model, paleta)."""
        self.model_id = model_id
        if hasattr(self, "mya_agent"):
            self.mya_agent.model_id = model_id
        self.provider = resolve_provider(model_id, provider)
        self.theme = f"mya-{self.provider}"

        try:
            status_bar = self.query_one("#status-bar", StatusLine)
            status_bar.set(
                project=getattr(self.session, "repository", None),
                branch=getattr(self.session, "branch", None),
                model=self.model_id,
                job=getattr(self.session, "current_job_id", None),
                dirty=not getattr(self.session, "working_tree_clean", True),
            )
        except Exception:
            pass

        try:
            welcome = self.query_one("#welcome", Welcome)
            welcome.model_id = model_id
        except Exception:
            pass

        if notify_chat and self.is_mounted:
            s = PROVIDERS.get(self.provider, PROVIDERS["mya"])
            conv = self.query_one("#conversation", VerticalScroll)
            conv.mount(
                ChatMessage(
                    Text.assemble(
                        (f"{s.glyph} ", f"bold {s.primary}"),
                        ("modelo ", MUTED),
                        self.model_id,
                    ),
                    role="tool",
                )
            )
            self.call_after_refresh(conv.scroll_end, animate=False)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="conversation", can_focus=False):
            yield Welcome(
                self.session,
                model_id=self.model_id,
                user_name=self._user_display_name,
                id="welcome",
            )
        with Vertical(id="bottom-dock"):
            yield CommandSuggestions(id="suggestions")
            with Horizontal(id="prompt-container"):
                yield Static(
                    Icons.PROMPT,
                    id="prompt-label",
                )
                yield PromptInput(
                    placeholder="describe qué quieres construir…",
                    id="prompt-input",
                )
            yield StatusLine(id="status-bar")

    def on_mount(self) -> None:
        """Aplica el tema por proveedor, inicializa la barra de estado y enfoca el prompt."""
        self.theme = f"mya-{self.provider}"
        try:
            status_bar = self.query_one("#status-bar", StatusLine)
            status_bar.set(
                project=getattr(self.session, "repository", None),
                branch=getattr(self.session, "branch", None),
                model=self.model_id,
                job=getattr(self.session, "current_job_id", None),
                dirty=not getattr(self.session, "working_tree_clean", True),
            )
        except Exception:
            pass

        from myagentos.setup.detector import needs_first_run

        if self.check_first_run and needs_first_run():
            from myagentos.ui.screens.first_run import FirstRunScreen

            self.push_screen(FirstRunScreen(), callback=self._on_first_run_complete)
        else:
            self._apply_saved_config()
            self._update_welcome_panel()
            self._prompt.focus()

    def _on_first_run_complete(self, config: Any) -> None:
        """Callback when first-run wizard completes."""
        if config is not None:
            if getattr(config, "user", None) and config.user.display_name:
                self._user_display_name = config.user.display_name
            if getattr(config, "mya", None) and config.mya.home:
                self._mya_home = Path(config.mya.home)
            if getattr(config, "model", None) and config.model.default:
                self.set_model(config.model.default)
            if getattr(config, "ui", None) and config.ui.theme:
                try:
                    ThemeRegistry.get_instance().set_active_theme(config.ui.theme)
                    if config.ui.theme != "default":
                        self.theme = PRESENTATION_TO_TEXTUAL.get(
                            config.ui.theme, f"mya-{self.provider}"
                        )
                except Exception:
                    pass

            self._update_welcome_panel()
            self._refresh_ui_model()
            msg = (
                f"[bold green]✓[/bold green] Bienvenido a Mya, "
                f"[bold]{self._user_display_name}[/bold]. "
                f"Entorno listo en [dim]{self._mya_home}[/dim]."
            )
            self._append_system_message(msg)
        self._prompt.focus()

    def _apply_saved_config(self) -> None:
        """Load and apply persisted config on normal startup."""
        from myagentos.config.loader import load_config

        config = load_config()
        if config:
            if config.user.display_name:
                self._user_display_name = config.user.display_name
            if config.mya.home:
                self._mya_home = Path(config.mya.home)
            if getattr(config, "model", None) and config.model.default:
                self.set_model(config.model.default)
            if getattr(config, "ui", None) and config.ui.theme and config.ui.theme != "default":
                try:
                    ThemeRegistry.get_instance().set_active_theme(config.ui.theme)
                    self.theme = PRESENTATION_TO_TEXTUAL.get(
                        config.ui.theme, f"mya-{self.provider}"
                    )
                except Exception:
                    pass

    def _update_welcome_panel(self) -> None:
        try:
            panel = self.query_one("#welcome", Welcome)
            panel.user_name = self._user_display_name
            panel.model_id = self.model_id
            panel.refresh_info()
        except Exception:
            pass

    # ── Prompt helpers ──────────────────────────────────────────────

    @property
    def _prompt(self) -> PromptInput:
        return self.query_one("#prompt-input", PromptInput)

    @property
    def _suggestions(self) -> CommandSuggestions:
        return self.query_one("#suggestions", CommandSuggestions)

    @property
    def _busy(self) -> bool:
        return self._active_worker is not None and self._active_worker.is_running

    def _fill_prompt(self, text: str, show_suggestions: bool = False) -> None:
        self._suppress_suggestions = not show_suggestions
        self._suggestions.display = False
        prompt = self._prompt
        prompt.value = text
        prompt.cursor_position = len(text)
        prompt.focus()

    @on(events.Click, "#prompt-container")
    @on(events.Click, "#prompt-label")
    @on(events.Click, "#status-bar")
    def _on_bottom_bar_click(self) -> None:
        self._prompt.focus()

    @on(Input.Changed, "#prompt-input")
    def _on_prompt_changed(self, event: Input.Changed) -> None:
        if self._suppress_suggestions:
            self._suppress_suggestions = False
            self._suggestions.display = False
            return
        self._suggestions.show_for(event.value)

    @on(PromptInput.Navigate)
    def _on_prompt_navigate(self, event: PromptInput.Navigate) -> None:
        if self._suggestions.display:
            self._suggestions.move(event.delta)
        else:
            self._navigate_history(event.delta)

    @on(PromptInput.Complete)
    def _on_prompt_complete(self) -> None:
        command = self._suggestions.selected_command
        if command:
            info = get_command_info(command)
            self._fill_prompt(f"{command} " if info and info.takes_argument else command)

    @on(OptionList.OptionSelected, "#suggestions")
    def _on_suggestion_clicked(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._accept_suggestion(event.option.id)

    @on(WelcomePanel.ActionRequested)
    def _on_welcome_action(self, event: WelcomePanel.ActionRequested) -> None:
        if event.submit:
            self._submit_text(event.text)
        else:
            self._fill_prompt(event.text)

    def _accept_suggestion(self, command: str) -> None:
        info = get_command_info(command)
        if info and info.args.startswith("<"):
            self._fill_prompt(f"{command} ")
        else:
            self._submit_text(command)

    def _navigate_history(self, delta: int) -> None:
        if not self._history:
            return
        if self._history_index == -1:
            if delta > 0:
                return
            self._history_draft = self._prompt.value
            self._history_index = len(self._history) - 1
        else:
            self._history_index += delta
            if self._history_index >= len(self._history):
                self._history_index = -1
                self._fill_prompt(self._history_draft)
                return
            self._history_index = max(0, self._history_index)
        self._fill_prompt(self._history[self._history_index])

    # ── Submission & Worker Execution ──────────────────────────────

    @on(Input.Submitted, "#prompt-input")
    def on_submit(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if self._suggestions.display:
            command = self._suggestions.selected_command
            if command and raw.lower() != command:
                self._accept_suggestion(command)
                return
        self._submit_text(raw)

    def _submit_text(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return
        if self._busy:
            self.notify("Mya todavía está respondiendo. Ctrl+C para cancelar.", severity="warning")
            return

        self._fill_prompt("")
        cmd = parse_input(raw)
        display_text = self._redact_secrets(cmd, raw)

        if not self._history or self._history[-1] != display_text:
            self._history.append(display_text)
        self._history_index = -1
        self._history_draft = ""

        self._append_user_message(display_text)
        self._active_worker = self.run_worker(
            self._run_command(cmd), group="mya", exclusive=True, exit_on_error=False
        )

    @staticmethod
    def _redact_secrets(cmd: ParsedCommand, raw: str) -> str:
        """Mask API keys in history and transcript."""
        if cmd.kind == SlashCommandKind.KEY:
            parts = cmd.argument.split(maxsplit=1)
            if len(parts) == 2:
                return f"{raw.split(maxsplit=1)[0]} {parts[0]} ••••••••"
        return raw

    async def _run_command(self, cmd: ParsedCommand) -> None:
        container = self.query_one("#prompt-container")
        container.add_class("-busy")
        try:
            await self._handle_command(cmd)
        except asyncio.CancelledError:
            self._append_system_message("Operación cancelada.")
            raise
        except Exception as err:
            self._append_error_message(f"{type(err).__name__}: {err}")
        finally:
            container.remove_class("-busy")

    async def _think(self, fn: Callable[..., T], *args: Any, label: str | None = None) -> T:
        """Run a blocking call off the UI thread while showing an animated indicator."""
        conv = self.query_one("#conversation", VerticalScroll)
        theme = ThemeRegistry.get_instance().active_theme
        indicator = Thinking(
            label=label,
            animate=MotionController.get_instance().allows_continuous_animation,
            ascii_only=theme.ascii_only,
        )
        await conv.mount(indicator)
        conv.scroll_end(animate=False)
        try:
            return await asyncio.to_thread(fn, *args)
        finally:
            await indicator.remove()

    async def _handle_command(self, cmd: ParsedCommand) -> None:
        """Route parsed commands to appropriate handlers."""
        match cmd.kind:
            case SlashCommandKind.EXIT:
                self.exit()

            case SlashCommandKind.HELP:
                self._append_mya_message(build_help())

            case SlashCommandKind.CLEAR:
                await self._clear_conversation()

            case SlashCommandKind.STATUS:
                self._show_status()

            case SlashCommandKind.CATEGORIZE:
                from myagentos.categorization import ProjectCategorizationService

                service = ProjectCategorizationService()
                profile = await self._think(
                    service.scan_project, self.session.repo_root, label="Analizando el proyecto"
                )
                self.session.project_profile = profile
                self.query_one("#welcome", WelcomePanel).refresh_info()
                tags_str = " ".join(f"#{t.label}" for t in profile.visible_tags)
                profile_lbl = f"[bold {Colors.PRIMARY}]Perfil:[/bold {Colors.PRIMARY}]"
                summary_lines = [
                    f"{profile_lbl} {profile.repository}",
                    f"[bold]Etiquetas:[/bold] {tags_str}",
                    f"[bold]Lenguajes:[/bold] {', '.join(profile.stack.languages) or 'N/A'}",
                    (
                        f"[bold]Frameworks:[/bold] "
                        f"{', '.join(profile.stack.frameworks) or 'ninguno'}"
                    ),
                    (
                        f"[bold]Tipo:[/bold] "
                        f"{', '.join(profile.architecture.application_type) or 'N/A'}"
                    ),
                    (
                        f"[bold]Tests:[/bold] "
                        f"{', '.join(profile.quality.test_frameworks) or 'ninguno'}"
                    ),
                ]
                self._append_mya_message("\n".join(summary_lines))

            case SlashCommandKind.PROJECTS:
                self.action_open_projects()

            case SlashCommandKind.MEMORY:
                await self._handle_memory_command(cmd.argument)

            case SlashCommandKind.SKILLS:
                await self._handle_skills_command(cmd.argument)

            case SlashCommandKind.INFO:
                obs = ObservabilityService()
                self._append_mya_message(
                    obs.render_info(
                        self.session,
                        gateway=self.gateway,
                        model_id=self.mya_agent.model_id,
                    )
                )

            case SlashCommandKind.TELEMETRY:
                obs = ObservabilityService()
                self._append_mya_message(obs.render_telemetry(self.session.current_job_id))

            case SlashCommandKind.MONITOR:
                obs = ObservabilityService()
                self._append_mya_message(
                    obs.render_monitor(self.session.current_job_id, self.session)
                )

            case SlashCommandKind.FAST:
                handler = CommandHandlerService()
                _, msg = await self._think(handler.handle_fast, cmd.argument)
                self._append_mya_message(msg)

            case SlashCommandKind.SCI_MODE:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_sci_mode, cmd.argument, label="Análisis científico en curso"
                )
                self._append_mya_message(res)

            case SlashCommandKind.DEEP_RESEARCH:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_deep_research, cmd.argument, label="Investigando a fondo"
                )
                self._append_mya_message(res)

            case SlashCommandKind.OPTIMIZE:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_optimize, cmd.argument, label="Revisando rendimiento"
                )
                self._append_mya_message(res)

            case SlashCommandKind.DECISION:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_decision, cmd.argument, label="Consultando 5 perspectivas"
                )
                self._append_mya_message(res)

            case SlashCommandKind.CLOUD:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_cloud, cmd.argument, label="Revisando arquitectura cloud"
                )
                self._append_mya_message(res)

            case SlashCommandKind.SECURITY:
                handler = CommandHandlerService()
                res = await self._think(
                    handler.handle_security, cmd.argument, label="Auditando seguridad"
                )
                self._append_mya_message(res)

            case SlashCommandKind.THEME:
                registry = ThemeRegistry.get_instance()
                arg = cmd.argument.strip().lower()
                badge = format_command_badge("/theme")
                if not arg:
                    avail = ", ".join(t.name for t in registry.list_themes())
                    curr = registry.active_theme.name
                    self._append_mya_message(
                        f"{badge} [bold]CONFIGURACIÓN DE TEMA[/bold]\n"
                        f"  Tema activo:  [bold green]{curr}[/bold green]\n"
                        f"  Disponibles:  {avail}\n\n"
                        "[dim]Uso: /theme <nombre_del_tema>[/dim]"
                    )
                else:
                    try:
                        th = registry.set_active_theme(arg)
                        self.theme = PRESENTATION_TO_TEXTUAL.get(th.name, "mya")
                        self._append_mya_message(
                            f"{badge} [bold]Tema cambiado a '{th.name}'[/bold]\n  {th.description}"
                        )
                    except ValueError as err:
                        self._append_mya_message(f"[bold red]Error:[/bold red] {err}")

            case SlashCommandKind.MOTION:
                ctrl = MotionController.get_instance()
                arg = cmd.argument.strip().lower()
                badge = format_command_badge("/motion")
                if not arg:
                    self._append_mya_message(
                        f"{badge} [bold]MODO DE ANIMACIÓN[/bold]\n"
                        f"  Actual: [bold green]{ctrl.mode.value}[/bold green]\n"
                        "  Modos:  full, reduced, off\n\n"
                        "[dim]Uso: /motion full|reduced|off[/dim]"
                    )
                else:
                    try:
                        mode = ctrl.set_mode(arg)
                        self._append_mya_message(
                            f"{badge} [bold]Nivel de animación: '{mode.value}'[/bold]"
                        )
                    except ValueError as err:
                        self._append_mya_message(f"[bold red]Error:[/bold red] {err}")

            case SlashCommandKind.AVATAR:
                arg = cmd.argument.strip().lower()
                valid_modes = ["dot", "glyph", "ascii", "minimal"]
                badge = format_command_badge("/avatar")
                if not arg:
                    curr = getattr(self, "_avatar_mode", "dot")
                    self._append_mya_message(
                        f"{badge} [bold]ESTILO DE AVATAR[/bold]\n"
                        f"  Actual: [bold green]{curr}[/bold green]\n"
                        f"  Modos:  {', '.join(valid_modes)}\n\n"
                        "[dim]Uso: /avatar dot|glyph|ascii|minimal[/dim]"
                    )
                elif arg not in valid_modes:
                    self._append_mya_message(
                        f"[bold red]Error:[/bold red] Modo de avatar '{arg}' desconocido. "
                        f"Elige entre: {', '.join(valid_modes)}"
                    )
                else:
                    self._avatar_mode = arg
                    renderer = get_mya_renderer(arg)
                    rs = MyaRenderState(
                        status="IDLE", label="Ready", expression="calm", avatar_mode=arg
                    )
                    theme = ThemeRegistry.get_instance().active_theme
                    preview = renderer.render_avatar(rs, ascii_only=theme.ascii_only)
                    self._append_mya_message(
                        f"{badge} [bold]Avatar cambiado a '{arg}':[/bold]\n\n{preview}"
                    )

            case SlashCommandKind.DENSITY:
                badge = format_command_badge("/density")
                arg = cmd.argument.strip().lower()
                if cmd.raw_input.strip().lower().startswith("/compact"):
                    arg = "compact"
                elif cmd.raw_input.strip().lower().startswith("/dense"):
                    arg = "comfortable"

                if arg in ("compact", "compacto"):
                    self.screen.add_class("-compact")
                    self._append_mya_message(
                        f"{badge} Densidad visual cambiada a [bold green]compacto[/bold green]."
                    )
                elif arg in ("comfortable", "dense", "cómodo", "comodo", "normal"):
                    self.screen.remove_class("-compact")
                    self._append_mya_message(
                        f"{badge} Densidad visual cambiada a [bold green]cómodo[/bold green]."
                    )
                else:
                    curr = "compacto" if self.screen.has_class("-compact") else "cómodo"
                    self._append_mya_message(
                        f"{badge} [bold]DENSIDAD VISUAL[/bold]\n"
                        f"  Actual: [bold green]{curr}[/bold green]\n"
                        "  Modos disponibles: compact, comfortable\n\n"
                        "[dim]Uso: /density compact|comfortable[/dim]"
                    )

            case SlashCommandKind.KEY:
                self._handle_key_command(cmd.argument)

            case SlashCommandKind.MODEL:
                self._handle_model_command(cmd.argument)

            case SlashCommandKind.NATURAL | SlashCommandKind.MYA:
                prompt = cmd.argument if cmd.kind == SlashCommandKind.MYA else cmd.raw_input
                await self._handle_natural_input(prompt.strip())

            case _:
                msg = (
                    f"[{Colors.DIM}]Comando /{cmd.kind.value} disponible "
                    f"en una versión futura.[/{Colors.DIM}]"
                )
                self._append_system_message(msg)

    def _save_env_var(self, key: str, value: str) -> None:
        """Safely saves or updates a key=value in .env file."""
        env_path = (self.session.repo_root or Path.cwd()) / ".env"
        lines: list[str] = []
        found = False
        if env_path.is_file():
            try:
                lines = env_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                lines = []

        new_lines: list[str] = []
        for line in lines:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key}={value}")

        try:
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _refresh_ui_model(self) -> None:
        """Refresh model display in status bar and welcome panel."""
        self._update_welcome_panel()
        try:
            status_bar = self.query_one("#status-bar", StatusLine)
            status_bar.set(
                project=getattr(self.session, "repository", None),
                branch=getattr(self.session, "branch", None),
                model=self.model_id,
                job=getattr(self.session, "current_job_id", None),
                dirty=not getattr(self.session, "working_tree_clean", True),
            )
        except Exception:
            pass

    def _handle_key_command(self, argument: str) -> None:
        """Handle /key and /keys commands to view or set API keys."""
        badge = format_command_badge("/key")
        args = argument.strip().split(maxsplit=1)

        def _mask(k: str) -> str:
            if not k:
                return "[dim]No configurada[/dim]"
            if len(k) <= 8:
                return f"[green]*** ({len(k)} chars)[/green]"
            return f"[bold green]{k[:6]}...{k[-4:]}[/bold green]"

        openai_key = os.getenv("OPENAI_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        if not args or not args[0]:
            claude_status = _mask(anthropic_key)
            openai_status = _mask(openai_key)
            gemini_status = _mask(gemini_key)
            active_model = self.mya_agent.model_id

            self._append_mya_message(
                f"{badge} [bold]CONFIGURACIÓN DE CLAVES API Y MODELOS[/bold]\n\n"
                f"  • [bold]Claude[/bold] (ANTHROPIC_API_KEY): {claude_status}\n"
                f"  • [bold]OpenAI[/bold] (OPENAI_API_KEY):    {openai_status}\n"
                f"  • [bold]Gemini[/bold] (GEMINI_API_KEY):    {gemini_status}\n"
                f"  • [bold]Modelo activo[/bold]:         [bold cyan]{active_model}[/bold cyan]\n"
                f"  • [bold]Archivo de claves[/bold]:        .env\n\n"
                f"[dim]Uso para configurar:[/dim]\n"
                f"  [bold]/key claude <tu_clave>[/bold]    Claude (activa claude-3-5-sonnet)\n"
                f"  [bold]/key openai <tu_clave>[/bold]    OpenAI (activa gpt-4o)\n"
                f"  [bold]/key gemini <tu_clave>[/bold]    Gemini (activa gemini-2.0-flash)\n"
                f"  [bold]/model <nombre>[/bold]           Cambiar modelo (ej: gpt-4o-mini)"
            )
            return

        provider = args[0].lower()
        if len(args) < 2 or not args[1].strip():
            self._append_mya_message(
                f"{badge} [bold yellow]Uso:[/bold yellow] /key {provider} <tu_api_key>\n"
                f"[dim]Ejemplo: /key openai sk-proj-...[/dim]"
            )
            return

        key_value = args[1].strip()

        if provider in ("openai", "chatgpt"):
            self._save_env_var("OPENAI_API_KEY", key_value)
            os.environ["OPENAI_API_KEY"] = key_value
            try:
                from myagentos.gateway.openai_adapter import OpenAIAdapter

                self.gateway.register_adapter("openai", OpenAIAdapter(api_key=key_value))
            except Exception as err:
                self._append_mya_message(
                    f"{badge} [bold red]Error al registrar OpenAIAdapter:[/bold red] {err}"
                )
                return

            self.gateway.discovery_cache.invalidate(provider="openai")
            profile = self.gateway.validate_credential("openai")

            if self.mya_agent.model_id in ("mock-mya", "mock"):
                self.set_model("gpt-4o", provider="openai")
                self._save_env_var("MYA_MODEL", "gpt-4o")
                os.environ["MYA_MODEL"] = "gpt-4o"
                self._refresh_ui_model()

            masked = _mask(key_value)
            status_str = (
                f"[bold green]✓ {profile.status.value}[/bold green]"
                if profile.status.value == "VALID"
                else f"[yellow]{profile.status.value}[/yellow]"
            )
            self._append_mya_message(
                f"{badge} [bold green]✓ Clave de OpenAI guardada exitosamente[/bold green]\n\n"
                f"  • Clave:         {masked}\n"
                f"  • Fingerprint:   [dim]{profile.fingerprint}[/dim]\n"
                f"  • Estado:        {status_str}\n"
                f"  • Persistencia:  .env\n"
                f"  • Proveedor:     'openai' activo\n"
                f"  • Modelo activo: [bold cyan]{self.mya_agent.model_id}[/bold cyan]"
            )

        elif provider in ("claude", "anthropic"):
            self._save_env_var("ANTHROPIC_API_KEY", key_value)
            os.environ["ANTHROPIC_API_KEY"] = key_value
            try:
                from myagentos.gateway.claude_adapter import ClaudeAdapter

                self.gateway.register_adapter("anthropic", ClaudeAdapter(api_key=key_value))
            except Exception as err:
                self._append_mya_message(
                    f"{badge} [bold red]Error al registrar ClaudeAdapter:[/bold red] {err}"
                )
                return

            self.gateway.discovery_cache.invalidate(provider="anthropic")
            profile = self.gateway.validate_credential("anthropic")

            if self.mya_agent.model_id in ("mock-mya", "mock"):
                self.set_model("claude-3-5-sonnet-latest", provider="claude")
                self._save_env_var("MYA_MODEL", "claude-3-5-sonnet-latest")
                os.environ["MYA_MODEL"] = "claude-3-5-sonnet-latest"
                self._refresh_ui_model()

            masked = _mask(key_value)
            status_str = (
                f"[bold green]✓ {profile.status.value}[/bold green]"
                if profile.status.value == "VALID"
                else f"[yellow]{profile.status.value}[/yellow]"
            )
            self._append_mya_message(
                f"{badge} [bold green]✓ Clave de Anthropic guardada exitosamente"
                "[/bold green]\n\n"
                f"  • Clave:         {masked}\n"
                f"  • Fingerprint:   [dim]{profile.fingerprint}[/dim]\n"
                f"  • Estado:        {status_str}\n"
                f"  • Persistencia:  .env\n"
                f"  • Proveedor:     'anthropic' activo\n"
                f"  • Modelo activo: [bold cyan]{self.mya_agent.model_id}[/bold cyan]"
            )

        elif provider in ("gemini", "google"):
            self._save_env_var("GEMINI_API_KEY", key_value)
            os.environ["GEMINI_API_KEY"] = key_value
            try:
                from myagentos.gateway.gemini_adapter import GeminiAdapter

                self.gateway.register_adapter("google", GeminiAdapter(api_key=key_value))
            except Exception as err:
                self._append_mya_message(
                    f"{badge} [bold red]Error al registrar GeminiAdapter:[/bold red] {err}"
                )
                return

            self.gateway.discovery_cache.invalidate(provider="google")
            profile = self.gateway.validate_credential("google")

            if self.mya_agent.model_id in ("mock-mya", "mock"):
                self.set_model("gemini-2.0-flash", provider="gemini")
                self._save_env_var("MYA_MODEL", "gemini-2.0-flash")
                os.environ["MYA_MODEL"] = "gemini-2.0-flash"
                self._refresh_ui_model()

            masked = _mask(key_value)
            status_str = (
                f"[bold green]✓ {profile.status.value}[/bold green]"
                if profile.status.value == "VALID"
                else f"[yellow]{profile.status.value}[/yellow]"
            )
            self._append_mya_message(
                f"{badge} [bold green]✓ Clave de Google Gemini guardada exitosamente"
                "[/bold green]\n\n"
                f"  • Clave:         {masked}\n"
                f"  • Fingerprint:   [dim]{profile.fingerprint}[/dim]\n"
                f"  • Estado:        {status_str}\n"
                f"  • Persistencia:  .env\n"
                f"  • Proveedor:     'google' activo\n"
                f"  • Modelo activo: [bold cyan]{self.mya_agent.model_id}[/bold cyan]"
            )
        else:
            self._append_mya_message(
                f"{badge} [bold red]Proveedor desconocido:[/bold red] '{provider}'. "
                f"Use: [bold]claude[/bold], [bold]openai[/bold] o [bold]gemini[/bold]."
            )

    def _handle_model_command(self, argument: str) -> None:
        """Handle /model command to view, discover, filter, or switch the active LLM (§10, §11, §12, §13)."""
        badge = format_command_badge("/model")
        arg = argument.strip()

        # Determine current provider from active model
        current_model = self.mya_agent.model_id
        current_provider = "mock"
        if (
            "gpt" in current_model
            or "o1" in current_model
            or "o3" in current_model
            or "openai" in current_model
        ):
            current_provider = "openai"
        elif "claude" in current_model or "anthropic" in current_model:
            current_provider = "anthropic"
        elif "gemini" in current_model or "google" in current_model:
            current_provider = "google"

        # Case 1: /model (no arguments) -> Show live catalog, credential status, identity (§10)
        if not arg:
            effective = self.gateway.get_effective_model_set(
                current_provider, active_model=current_model
            )
            profile = self.gateway.get_credential_profile(current_provider)
            status_val = profile.status.value if profile else "UNKNOWN"
            status_icon = "✓" if status_val == "VALID" else "✗"
            status_color = "green" if status_val == "VALID" else "red"

            lines = [
                f"{badge} [bold]MODELOS DISPONIBLES[/bold]\n",
                f"  • Provider:      [bold]{current_provider.capitalize()}[/bold]",
                f"  • Credential:    [{status_color}]{status_icon} {status_val}[/{status_color}]",
            ]
            if profile:
                lines.append(f"  • Fingerprint:   [dim]{profile.fingerprint}[/dim]")
                if profile.identity:
                    if profile.identity.organization:
                        lines.append(f"  • Organization:  {profile.identity.organization}")
                    if profile.identity.project:
                        lines.append(f"  • Project:       {profile.identity.project}")
                    if profile.identity.quota_scope:
                        lines.append(f"  • Quota Scope:   {profile.identity.quota_scope}")
                    if not (
                        profile.identity.organization
                        or profile.identity.project
                        or profile.identity.quota_scope
                    ):
                        lines.append("  • Identity:      Not provided by provider")
                else:
                    lines.append("  • Identity:      Not provided by provider")

            lines.append("\n[bold]Catálogo accesible:[/bold]")
            if effective.available_models:
                for mid in effective.available_models:
                    prefix = "  [bold cyan]> " if mid == current_model else "    "
                    suffix = " (activo)[/bold cyan]" if mid == current_model else ""
                    lines.append(f"{prefix}{mid}{suffix}")
            else:
                lines.append("  [dim]No hay modelos disponibles con la credencial activa.[/dim]")

            if effective.restricted_models:
                lines.append(
                    f"\n[dim]Modelos restringidos para esta credencial: {', '.join(effective.restricted_models)}[/dim]"
                )

            lines.extend(
                [
                    "",
                    "[dim]Uso:[/dim]",
                    "  • [bold]/model <id>[/bold]        Seleccionar modelo (ej: gpt-4o, claude-3-5-sonnet-latest)",
                    "  • [bold]/model <filtro>[/bold]    Filtrar catálogo (ej: /model coder, /model mini)",
                    "  • [bold]/model refresh[/bold]     Actualizar catálogo en vivo desde el proveedor",
                ]
            )
            self._append_mya_message("\n".join(lines))
            return

        # Case 2: /model refresh -> Force live discovery (§13)
        if arg.lower() == "refresh":
            effective = self.gateway.get_effective_model_set(
                current_provider, active_model=current_model, force_refresh=True
            )
            disc = self.gateway.discover_models(current_provider)
            disc_count = len(disc.models) if disc else len(effective.available_models)
            comp_count = len(effective.available_models)
            filt_count = len(effective.policy_filtered_models)

            lines = [
                f"{badge} [bold green]✓ Catálogo actualizado desde el proveedor[/bold green]\n",
                f"  • Descubiertos:  {disc_count} modelos",
                f"  • Compatibles:   {comp_count}",
                f"  • Filtrados:     {filt_count} por política/ciclo de vida\n",
                "[bold]Modelos disponibles:[/bold]",
            ]
            for mid in effective.available_models:
                prefix = "  [bold cyan]> " if mid == current_model else "    "
                suffix = " (activo)[/bold cyan]" if mid == current_model else ""
                lines.append(f"{prefix}{mid}{suffix}")

            self._append_mya_message("\n".join(lines))
            return

        # Case 3: /model <id> or /model <query>
        arg_lower = arg.lower()
        target_provider = current_provider
        if arg_lower.startswith("mock"):
            target_provider = "mock"
        elif "claude" in arg_lower or "anthropic" in arg_lower:
            target_provider = "anthropic"
        elif "gpt" in arg_lower or "o1" in arg_lower or "o3" in arg_lower:
            target_provider = "openai"
        elif "gemini" in arg_lower:
            target_provider = "google"

        # Check adapter presence for target provider
        if target_provider != current_provider and target_provider not in self.gateway.adapters:
            env_var = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "google": "GEMINI_API_KEY",
            }.get(target_provider, "")
            self._append_mya_message(
                f"{badge} [bold yellow]Advertencia:[/bold yellow] El proveedor '{target_provider}' "
                f"no tiene adaptador configurado para '{arg}'.\n"
                f"Configure la clave ejecutando: [bold]/key {target_provider} <su_clave>[/bold] "
                f"(o defina {env_var} en su entorno/.env)."
            )
            return

        effective = self.gateway.get_effective_model_set(
            target_provider, active_model=current_model
        )

        # Check if arg directly matches an available model ID (case-insensitive)
        matched_id = next((m for m in effective.available_models if m.lower() == arg_lower), None)
        if matched_id:
            self.set_model(matched_id, provider=target_provider, notify_chat=True)
            self._save_env_var("MYA_MODEL", matched_id)
            os.environ["MYA_MODEL"] = matched_id
            self._refresh_ui_model()

            self._append_mya_message(
                f"{badge} [bold green]✓ Modelo cambiado a:[/bold green] [bold cyan]{matched_id}[/bold cyan]\n"
                f"  • Proveedor: '{target_provider}'\n"
                f"  • Persistencia: .env (MYA_MODEL={matched_id})"
            )
            return

        # Guarded check: Is it in restricted or policy filtered models, or credential invalid? (§12)
        if arg_lower in [m.lower() for m in effective.restricted_models]:
            self._append_mya_message(
                f'{badge} [bold red]No puedes utilizar "{arg}" con la credencial activa.[/bold red]\n\n'
                f"Estado:\n[bold yellow]NO DISPONIBLE[/bold yellow]\n\n"
                f"Motivo:\nLa credencial actual no tiene acceso a este modelo."
            )
            return

        if arg_lower in [m.lower() for m in effective.policy_filtered_models]:
            self._append_mya_message(
                f'{badge} [bold red]No puedes utilizar "{arg}" con la credencial activa.[/bold red]\n\n'
                f"Estado:\n[bold yellow]FILTRADO[/bold yellow]\n\n"
                f"Motivo:\nEl modelo está retirado o filtrado por política del sistema."
            )
            return

        from myagentos.gateway.credentials import CredentialStatus

        if effective.credential_status in (CredentialStatus.INVALID, CredentialStatus.REVOKED):
            self._append_mya_message(
                f'{badge} [bold red]No puedes utilizar "{arg}" con la credencial activa.[/bold red]\n\n'
                f"Estado:\n[bold yellow]NO DISPONIBLE[/bold yellow]\n\n"
                f"Motivo:\nLa credencial para '{target_provider}' no es válida o fue revocada."
            )
            return

        # Otherwise, treat as filter query (§11)
        query_matches = [m for m in effective.available_models if arg_lower in m.lower()]
        if query_matches:
            lines = [
                f'{badge} [bold]MODELOS DISPONIBLES[/bold] [dim](filtro: "{arg}")[/dim]\n',
                f"  • Provider:   [bold]{target_provider.capitalize()}[/bold]\n",
            ]
            for mid in query_matches:
                prefix = "  [bold cyan]> " if mid == current_model else "    "
                suffix = " (activo)[/bold cyan]" if mid == current_model else ""
                lines.append(f"{prefix}{mid}{suffix}")
            lines.extend(
                [
                    "",
                    "[dim]Para seleccionar uno: /model <nombre_exacto>[/dim]",
                ]
            )
            self._append_mya_message("\n".join(lines))
            return

        # No model matched and query returned nothing
        self._append_mya_message(
            f"{badge} [bold yellow]No se encontraron modelos disponibles que coincidan con:[/bold yellow] '{arg}'\n"
            f"[dim]Ejecute /model para ver la lista completa o /model refresh para actualizar.[/dim]"
        )

    async def _handle_memory_command(self, argument: str) -> None:
        """Handle /memory command to inspect or query Project and User memory (§46)."""
        badge = format_command_badge("/memory")
        arg = argument.strip()
        mgr = getattr(self.mya_agent, "memory_manager", None)
        active_proj = (
            getattr(self.session, "project_id", None)
            or getattr(self.session, "repository", None)
            or "global"
        )
        if not arg or arg.lower() == "status":
            if mgr:
                user_rec = mgr.retrieve(
                    user_id=getattr(self.session, "user_id", None),
                    project_id=None,
                    session_id=None,
                    query="",
                    limit=50,
                )
                proj_rec: list[Any] = (
                    mgr.retrieve(
                        user_id=None,
                        project_id=active_proj,
                        session_id=None,
                        query="",
                        limit=50,
                    )
                    if active_proj
                    else []
                )
                sess_rec = mgr.retrieve(
                    user_id=None,
                    project_id=None,
                    session_id=self.session.session_id,
                    query="",
                    limit=50,
                )
                self._append_mya_message(
                    f"{badge} [bold]MEMORIA DEL SISTEMA[/bold]\n"
                    f"  Proyecto activo: [bold green]{active_proj}[/bold green]\n"
                    f"  • Memoria de Proyecto: [bold]{len(proj_rec)}[/bold] hechos verificados\n"
                    f"  • Memoria de Usuario:  [bold]{len(user_rec)}[/bold] hechos/preferencias\n"
                    f"  • Memoria de Sesión:   [bold]{len(sess_rec)}[/bold] entradas en el turno actual\n\n"
                    "[dim]Uso: /memory search <término> | /memory[/dim]"
                )
            else:
                self._append_mya_message(
                    f"{badge} Memoria compartida activa para el proyecto [bold]{active_proj}[/bold]."
                )
        elif arg.lower().startswith("search "):
            query = arg[7:].strip()
            if mgr and query:
                records = mgr.retrieve(
                    user_id=getattr(self.session, "user_id", None),
                    project_id=active_proj,
                    session_id=self.session.session_id,
                    query=query,
                    limit=5,
                )
                if records:
                    lines = [f"{badge} [bold]Coincidencias en memoria para '{query}':[/bold]"]
                    for r in records:
                        lines.append(f"  • [{r.scope.upper()}] {r.content[:120]}")
                    self._append_mya_message("\n".join(lines))
                else:
                    self._append_mya_message(
                        f"{badge} No se encontraron hechos de memoria para '{query}'."
                    )
            else:
                self._append_mya_message(f"{badge} Consulta vacía o servicio no disponible.")
        else:
            self._append_mya_message(
                f"{badge} Subcomando no reconocido. Uso: /memory [search <término>]"
            )

    async def _handle_skills_command(self, argument: str) -> None:
        """Handle /skills command to discover and inspect capabilities (§57, §58)."""
        badge = format_command_badge("/skills")
        arg = argument.strip()
        from myagentos.skills.registry import SkillRegistry

        registry = getattr(self.mya_agent, "skill_registry", None) or SkillRegistry()
        project_root = getattr(self.session, "repo_root", None)
        registry.discover(project_root=project_root)
        all_skills = registry.list_all_definitions()

        if not arg or arg.lower() in ("list", "all"):
            lines = [
                f"{badge} [bold]CATÁLOGO DE SKILLS (CAPACIDADES)[/bold]\n"
                "  Capacidades JIT descubiertas en el sistema:\n"
            ]
            if all_skills:
                for s in all_skills:
                    tags = " ".join(f"#{t}" for t in s.tags[:3])
                    src_tag = f"[dim cyan][{s.source}][/dim cyan]"
                    lines.append(
                        f"  • {src_tag} [bold {Colors.PRIMARY}]{s.name}[/bold {Colors.PRIMARY}] "
                        f"({s.version}) {tags}\n    [dim]{s.description}[/dim]"
                    )
            else:
                lines.append("  • [dim]No hay skills registradas actualmente.[/dim]")
            lines.append("\n[dim]Uso: /skills | /skills search <query> | /skills show <skill>[/dim]")
            self._append_mya_message("\n".join(lines))
        elif arg.lower().startswith("search "):
            query = arg[7:].strip().lower()
            matches = [
                s
                for s in all_skills
                if query in s.name.lower()
                or query in s.description.lower()
                or any(query in tag.lower() for tag in s.tags)
            ]
            if matches:
                lines = [f"{badge} [bold]Skills coincidentes con '{query}':[/bold]"]
                for s in matches:
                    src_tag = f"[{s.source}]"
                    lines.append(f"  • {src_tag} [bold]{s.name}[/bold]: {s.description}")
                self._append_mya_message("\n".join(lines))
            else:
                self._append_mya_message(f"{badge} No se encontraron skills para '{query}'.")
        elif arg.lower().startswith("show "):
            target = arg[5:].strip().lower()
            defn = registry.get_definition(target)
            if defn:
                active = registry.load(defn.name)
                preview = (active.content[:300] + "...") if active else "Sin contenido."
                tags_str = ", ".join(f"#{t}" for t in defn.tags) if defn.tags else "ninguna"
                req_str = ", ".join(defn.requires) if defn.requires else "ninguna"
                lines = [
                    f"{badge} [bold {Colors.PRIMARY}]SKILL: {defn.name}[/bold {Colors.PRIMARY}] "
                    f"([dim]{defn.source}[/dim] v{defn.version})",
                    f"  {defn.description}",
                    f"  • Etiquetas: [cyan]{tags_str}[/cyan]",
                    f"  • Requiere: [yellow]{req_str}[/yellow]",
                    f"  • Suelo de riesgo: [magenta]{defn.risk_floor}[/magenta]",
                    "",
                    f"[dim]{preview}[/dim]",
                ]
                self._append_mya_message("\n".join(lines))
            else:
                self._append_mya_message(f"{badge} Skill '{target}' no encontrada en el registry.")
        else:
            self._append_mya_message(
                f"{badge} Subcomando no reconocido. Uso: /skills | /skills search <query> | /skills show <skill>"
            )

    async def _handle_natural_input(self, text: str) -> None:
        """Handle conversational or task intent input from the user."""
        text_lower = text.lower().strip()
        actionable_markers = [
            "añade",
            "añadir",
            "anade",
            "agrega",
            "agregar",
            "crea",
            "crear",
            "corrige",
            "corregir",
            "arregla",
            "arreglar",
            "cambia",
            "cambiar",
            "modifica",
            "modificar",
            "elimina",
            "eliminar",
            "borra",
            "borrar",
            "implementa",
            "implementar",
            "refactoriza",
            "refactorizar",
            "optimiza",
            "optimizar",
            "instala",
            "instalar",
            "actualiza",
            "actualizar",
            "configura",
            "configurar",
            "haz",
            "make",
            "add ",
            "create ",
            "fix ",
            "change ",
            "modify ",
            "delete ",
            "implement ",
            "refactor ",
            "optimize ",
            "install ",
            "update ",
            "configure ",
        ]
        is_action_request = any(marker in text_lower for marker in actionable_markers)

        if not is_action_request:
            response = await self._think(self._converse, text)
            self._append_mya_message(response)
            self._record_conversation_turn(text, response)
            return

        # Interpret intent through Mya LLM
        result = await self._think(self._interpret, text, label="Interpretando tu petición")
        if result.resolved and result.intent:
            commentary = (
                result.explanation
                or f"Entendido. Interpreto que quieres: «{result.intent.objective}»."
            )
            self._append_mya_message(commentary)
            self._record_conversation_turn(text, commentary)
        elif result.questions:
            lines = [
                result.explanation or "Necesito aclarar algunos detalles antes de proceder:",
                "",
            ]
            for q in result.questions:
                lines.append(f"  • {q}")
            response = "\n".join(lines)
            self._append_mya_message(response)
            self._record_conversation_turn(text, response)
        else:
            response = await self._think(self._converse, text)
            self._append_mya_message(response)
            self._record_conversation_turn(text, response)

    def _record_conversation_turn(self, user_text: str, assistant_text: str) -> None:
        """Keep recent natural-language turns available to Mya's conversation channel."""
        project_id = self.mya_agent.memory_manager.project_id_for_session(self.session)
        self._conversation_history.extend(
            [
                {"role": "user", "content": user_text, "project_id": project_id or ""},
                {"role": "assistant", "content": assistant_text, "project_id": project_id or ""},
            ]
        )
        del self._conversation_history[:-12]

    def _converse(self, text: str) -> str:
        return self.mya_agent.converse(
            text,
            session=self.session,
            history=self._conversation_history,
        )

    def _interpret(self, text: str) -> Any:
        return self.mya_agent.interpret(text, session=self.session)

    def _show_status(self) -> None:
        """Show current project status."""
        s = self.session
        status = (
            f"[{Colors.SUCCESS}]● limpio[/{Colors.SUCCESS}]"
            if s.working_tree_clean
            else f"[{Colors.WARNING}]● cambios sin commit[/{Colors.WARNING}]"
        )

        lines = [
            f"[bold]Proyecto:[/bold]  {s.repository or 'sin proyecto'}",
            f"[bold]Rama:[/bold]      {s.branch or 'N/A'}",
            f"[bold]Commit:[/bold]    {s.commit_short or 'N/A'}",
            f"[bold]Estado:[/bold]    {status}",
            f"[bold]Sesión:[/bold]    {s.session_id}",
        ]

        if s.current_job_id:
            lines.append(f"[bold]Job:[/bold]       {s.current_job_id}")

        self._append_mya_message("\n".join(lines))

    # ── Conversation rendering ──────────────────────────────────────

    def _append_message(
        self,
        content: RenderableType,
        role: MessageRole,
        provider: str | None = None,
        copy_text: str | None = None,
    ) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        prov = provider or (self.provider if role in ("mya", "agent") else None)
        conv.mount(ChatMessage(content, role=role, provider=prov, copy_text=copy_text))
        self.call_after_refresh(conv.scroll_end, animate=False)

    def _append_user_message(self, text: str) -> None:
        """Add a user message; slash commands get their category badge."""
        formatted_text = text
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            arg_part = f" {parts[1]}" if len(parts) > 1 else ""
            formatted_text = f"{format_command_badge(parts[0])}{arg_part}"
        self._append_message(formatted_text, "user")

    def _append_mya_message(self, content: RenderableType) -> None:
        rendered: RenderableType = content
        if isinstance(content, str) and not content.startswith("["):
            rendered = Markdown(content)
        copy_text = content if isinstance(content, str) else None
        self._append_message(rendered, "agent", provider=self.provider, copy_text=copy_text)

    @on(ChatMessage.CopyRequested)
    def _copy_chat_message(self, event: ChatMessage.CopyRequested) -> None:
        """Copy a Mya response using Textual's native clipboard integration."""
        try:
            if sys.platform == "darwin":
                _copy_to_macos_clipboard(event.text)
            self.copy_to_clipboard(event.text)
            self.notify("Respuesta copiada", timeout=1.5)
        except Exception as exc:
            self.notify(f"No se pudo copiar la respuesta: {exc}", severity="error", timeout=2)

    def _append_tool_message(self, content: RenderableType) -> None:
        self._append_message(content, "tool")

    def _append_system_message(self, text: str) -> None:
        self._append_message(text, "system")

    def _append_error_message(self, text: str) -> None:
        self._append_message(text, "error")

    async def _clear_conversation(self) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        self._conversation_history.clear()
        await conv.remove_children([child for child in conv.children if child.id != "welcome"])

    # ── Actions ─────────────────────────────────────────────────────

    def action_cancel(self) -> None:
        """Ctrl+C — cancel running worker, clear input, or offer to cancel job."""
        if self._busy and self._active_worker is not None:
            self._active_worker.cancel()
        elif self._prompt.value:
            self._fill_prompt("")
        elif self.session.current_job_id:
            self._append_mya_message(
                f"¿Detener el job {self.session.current_job_id}?\n\n\\[A] Detener   \\[N] Continuar"
            )
        else:
            self.notify("Pulsa Ctrl+D para salir.", timeout=2)

    def action_escape(self) -> None:
        """Escape — close suggestions first, then clear prompt."""
        if self._suggestions.display:
            self._suggestions.display = False
        else:
            self._fill_prompt("")

    async def action_clear_conversation(self) -> None:
        await self._clear_conversation()

    def action_show_commands(self) -> None:
        self._submit_text("/help")

    async def action_next_model(self) -> None:
        """F2 — Cycle through models on the fly (§ demo_ui.py)."""
        demo_models = ["mock-mya", "claude-sonnet-5-5", "gpt-5", "gemini-2.5-pro", "llama3.1"]
        curr = self.model_id
        try:
            idx = demo_models.index(curr)
            next_idx = (idx + 1) % len(demo_models)
        except ValueError:
            next_idx = 0
        next_model = demo_models[next_idx]
        self.set_model(next_model, notify_chat=True)

    def action_open_projects(self) -> None:
        """Open the Project Explorer screen."""

        def on_return(_: Any = None) -> None:
            try:
                self.query_one("#welcome", WelcomePanel).refresh_info()
                status_bar = self.query_one("#status-bar", StatusLine)
                status_bar.set(
                    project=getattr(self.session, "repository", None),
                    branch=getattr(self.session, "branch", None),
                    model=self.model_id,
                    job=getattr(self.session, "current_job_id", None),
                    dirty=not getattr(self.session, "working_tree_clean", True),
                )
            except Exception:
                pass
            self._prompt.focus()

        self.push_screen(ProjectsScreen(session=self.session), on_return)

    async def action_quit(self) -> None:
        if self._busy and self._active_worker is not None:
            self._active_worker.cancel()
        self.exit()


def run(repo_path: str | None = None) -> None:
    """Entry point for the `mya` command."""
    path = Path(repo_path).resolve() if repo_path else None
    app = MyaApp(repo_path=path)
    app.run()


if __name__ == "__main__":
    run()
