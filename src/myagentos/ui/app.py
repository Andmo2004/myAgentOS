"""Mya — Interactive terminal application for Agentic OS.

This is the main entry point for the `mya` command.
Built on Textual. The UI is a derived view of the Event Store.
The UI contains no security logic and sends commands to the Job Controller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from myagentos.gateway.client import ModelGateway
from myagentos.mya.agent import MyaAgent
from myagentos.ui.commands import (
    ParsedCommand,
    SlashCommandKind,
    parse_input,
)
from myagentos.ui.screens.projects import ProjectsScreen
from myagentos.ui.session import Session, create_session
from myagentos.ui.themes import Colors, Icons

HELP_TEXT = """\
[bold cyan]Talk naturally:[/bold cyan]
  "añade autenticación"
  "arregla los tests"
  "continúa este proyecto"
  "muéstrame mis proyectos"

[bold cyan]Commands:[/bold cyan]
  /projects    project explorer & management
  /status      project status
  /categorize  scan & profile project
  /jobs        active jobs
  /diff        view diff
  /cancel      cancel current job
  /help        this help
  /exit        exit mya

[bold cyan]Advanced:[/bold cyan]
  /model     model configuration
  /usage     token and cost usage
  /debug     internal state
"""


class WelcomePanel(Static):
    """Welcome panel showing repository information (§5)."""

    def __init__(self, session: Session, *args: Any, **kwargs: Any) -> None:
        self.session = session
        super().__init__(*args, **kwargs)

    def render(self) -> str:
        s = self.session
        status = (
            f"[{Colors.SUCCESS}]clean[/{Colors.SUCCESS}]"
            if s.working_tree_clean
            else f"[{Colors.WARNING}]dirty[/{Colors.WARNING}]"
        )

        repo_line = f"  Repository   [bold]{s.repository or 'no repository'}[/bold]"
        branch_line = f"  Branch       [{Colors.PRIMARY}]{s.branch or 'N/A'}[/{Colors.PRIMARY}]"
        commit_line = f"  Commit       [{Colors.DIM}]{s.commit_short or 'N/A'}[/{Colors.DIM}]"
        status_line = f"  Status       {status}"

        lines = [
            "",
            f"[bold {Colors.PRIMARY}]                     MYA · Agentic OS[/bold {Colors.PRIMARY}]",
            "",
            repo_line,
            branch_line,
            commit_line,
            status_line,
        ]

        if s.project_profile and s.project_profile.visible_tags:
            tags_str = " ".join(
                f"[{Colors.PRIMARY}][{t.label}][/{Colors.PRIMARY}]"
                for t in s.project_profile.visible_tags
            )
            lines.append(f"  Profile      {tags_str}")

        lines.extend(
            [
                "",
                f"  [{Colors.DIM}]Ready. Describe what you want to build or fix.[/{Colors.DIM}]",
                "",
                (
                    f"  [{Colors.DIM}]/help[/{Colors.DIM}]  commands    "
                    f"[{Colors.DIM}]/projects[/{Colors.DIM}]  projects    "
                    f"[{Colors.DIM}]/status[/{Colors.DIM}]  status    "
                    f"[{Colors.DIM}]/categorize[/{Colors.DIM}]  tags"
                ),
                "",
            ]
        )
        return "\n".join(lines)


class MyaApp(App[None]):
    """Mya — Agentic OS interactive terminal interface.

    Mya is the voice of the operating system.
    Competent, calm, slightly ironic, and always useful.
    """

    TITLE = "Mya · Agentic OS"

    CSS = """
    Screen {
        layout: vertical;
    }

    #welcome {
        height: auto;
        border: round $primary;
        margin: 1 2;
        padding: 0 1;
    }

    #conversation {
        height: 1fr;
        margin: 0 2;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #status-bar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
    }

    #prompt-container {
        height: 3;
        dock: bottom;
        padding: 0 2;
    }

    #prompt-input {
        width: 1fr;
    }

    .mya-message {
        margin: 0 0 1 0;
    }

    .user-message {
        margin: 0 0 1 0;
        color: $text;
    }

    .system-message {
        margin: 0 0 1 0;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+d", "quit", "Exit", show=False),
        Binding("ctrl+p", "open_projects", "Projects", show=True),
        Binding("escape", "escape", "Escape", show=False),
    ]

    def __init__(
        self,
        repo_path: Path | None = None,
        gateway: ModelGateway | None = None,
        model_id: str = "mock-mya",
    ) -> None:
        super().__init__()
        self.session = create_session(repo_path)
        self.gateway = gateway or ModelGateway()
        if "mock" not in self.gateway.adapters:
            from myagentos.gateway.mock_adapter import MockProviderAdapter

            self.gateway.register_adapter("mock", MockProviderAdapter())
        self.mya_agent = MyaAgent(gateway=self.gateway, model_id=model_id)
        self._history: list[str] = []
        self._history_index: int = -1

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield WelcomePanel(self.session, id="welcome")
        yield VerticalScroll(id="conversation")
        yield Static(self._render_status_bar(), id="status-bar")
        with Horizontal(id="prompt-container"):
            yield Static(
                f"[bold {Colors.PRIMARY}]{Icons.PROMPT}[/bold {Colors.PRIMARY}] ",
                id="prompt-label",
            )
            yield Input(
                placeholder="Describe what you need...",
                id="prompt-input",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Focus the input prompt on startup."""
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted, "#prompt-input")
    async def on_submit(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        raw = event.value.strip()
        if not raw:
            return

        # Clear input
        inp = self.query_one("#prompt-input", Input)
        inp.value = ""

        # Add to history
        self._history.append(raw)
        self._history_index = -1

        # Display user message
        self._append_user_message(raw)

        # Parse and handle
        cmd = parse_input(raw)
        await self._handle_command(cmd)

    async def _handle_command(self, cmd: ParsedCommand) -> None:
        """Route parsed commands to handlers."""
        match cmd.kind:
            case SlashCommandKind.EXIT:
                self.exit()

            case SlashCommandKind.HELP:
                self._append_mya_message(HELP_TEXT)

            case SlashCommandKind.CLEAR:
                conv = self.query_one("#conversation", VerticalScroll)
                await conv.remove_children()

            case SlashCommandKind.STATUS:
                self._show_status()

            case SlashCommandKind.CATEGORIZE:
                from myagentos.categorization import ProjectCategorizationService

                service = ProjectCategorizationService()
                profile = service.scan_project(self.session.repo_root)
                self.session.project_profile = profile
                tags_str = " ".join(f"[{t.label}]" for t in profile.visible_tags)
                stat_upper = profile.status.value.upper()
                langs_str = ", ".join(profile.stack.languages) or "N/A"
                fws_str = ", ".join(profile.stack.frameworks) or "none"
                apps_str = ", ".join(profile.architecture.application_type) or "N/A"
                tests_str = ", ".join(profile.quality.test_frameworks) or "none"
                type_check = "✓" if profile.quality.typechecking else "✗"
                lint_check = "✓" if profile.quality.linting else "✗"
                summary_lines = [
                    f"[bold cyan]Project Profile:[/bold cyan] {profile.repository} ({stat_upper})",
                    f"[bold]Visible Tags:[/bold] {tags_str}",
                    f"[bold]Languages:[/bold] {langs_str}",
                    f"[bold]Frameworks:[/bold] {fws_str}",
                    f"[bold]Type:[/bold] {apps_str}",
                    f"[bold]Quality:[/bold] Tests: {tests_str}",
                    f"[bold]Checks:[/bold] Typing: {type_check} | Linting: {lint_check}",
                ]
                self._append_mya_message("\n".join(summary_lines))

            case SlashCommandKind.PROJECTS:
                self.action_open_projects()

            case SlashCommandKind.NATURAL | SlashCommandKind.MYA:
                prompt = cmd.argument if cmd.kind == SlashCommandKind.MYA else cmd.raw_input
                await self._handle_natural_input(prompt.strip())

            case _:
                self._append_system_message(
                    f"[{Colors.DIM}]Command /{cmd.kind.value} "
                    f"will be available in a future version.[/{Colors.DIM}]"
                )

    async def _handle_natural_input(self, text: str) -> None:
        """Handle natural language input — route through Mya LLM."""
        if not text:
            return

        # Distinguish conversational dialogue vs task interpretation
        lower = text.lower()
        conversational_starters = [
            "hola",
            "buenas",
            "hello",
            "hi",
            "quién eres",
            "quien eres",
            "cómo estás",
            "como estas",
            "qué puedes hacer",
            "gracias",
        ]
        action_keywords = [
            "arregla",
            "crea",
            "añade",
            "modifica",
            "test",
            "elimina",
            "refactor",
            "cambia",
        ]
        is_pure_conversation = any(c in lower for c in conversational_starters) and not any(
            a in lower for a in action_keywords
        )

        if is_pure_conversation:
            response = self.mya_agent.converse(text, session=self.session)
            self._append_mya_message(response)
            return

        # Interpret intent through Mya LLM
        result = self.mya_agent.interpret(text, session=self.session)
        if result.resolved and result.intent:
            commentary = (
                result.explanation
                or "Entendido. He sintetizado el objetivo para el Job Controller."
            )
            lines = [
                commentary,
                "",
                f"[bold]Objetivo:[/bold] {result.intent.objective}",
            ]
            if result.intent.constraints:
                lines.append(f"[bold]Restricciones:[/bold] {', '.join(result.intent.constraints)}")
            if result.intent.repository_scope:
                lines.append(f"[bold]Alcance:[/bold] {result.intent.repository_scope}")
            lines.append(f"[bold]Modo:[/bold] {result.intent.requested_mode.value}")
            lines.extend(
                [
                    "",
                    f"[{Colors.DIM}]UserIntent entregado al Job Controller.[/{Colors.DIM}]",
                ]
            )
            self._append_mya_message("\n".join(lines))
        elif result.questions:
            lines = [
                result.explanation or "Necesito aclarar algunos detalles antes de proceder:",
                "",
            ]
            for q in result.questions:
                lines.append(f"  • {q}")
            self._append_mya_message("\n".join(lines))
        else:
            response = self.mya_agent.converse(text, session=self.session)
            self._append_mya_message(response)

    def _show_status(self) -> None:
        """Show current project status."""
        s = self.session
        status = (
            f"[{Colors.SUCCESS}]clean[/{Colors.SUCCESS}]"
            if s.working_tree_clean
            else f"[{Colors.WARNING}]dirty[/{Colors.WARNING}]"
        )

        lines = [
            f"[bold]Project:[/bold]  {s.repository or 'none'}",
            f"[bold]Branch:[/bold]   {s.branch or 'N/A'}",
            f"[bold]Commit:[/bold]   {s.commit_short or 'N/A'}",
            f"[bold]Status:[/bold]   {status}",
            f"[bold]Session:[/bold]  {s.session_id}",
        ]

        if s.current_job_id:
            lines.append(f"[bold]Job:[/bold]      {s.current_job_id}")

        self._append_mya_message("\n".join(lines))

    def _append_user_message(self, text: str) -> None:
        """Add a user message to the conversation."""
        conv = self.query_one("#conversation", VerticalScroll)
        msg = Static(
            f"[bold]{Icons.PROMPT}[/bold] {text}",
            classes="user-message",
        )
        conv.mount(msg)
        msg.scroll_visible()

    def _append_mya_message(self, text: str) -> None:
        """Add a Mya message to the conversation."""
        conv = self.query_one("#conversation", VerticalScroll)
        msg = Static(
            f"[bold {Colors.PRIMARY}]Mya {Icons.ARROW}[/bold {Colors.PRIMARY}] {text}",
            classes="mya-message",
        )
        conv.mount(msg)
        msg.scroll_visible()

    def _append_system_message(self, text: str) -> None:
        """Add a system message to the conversation."""
        conv = self.query_one("#conversation", VerticalScroll)
        msg = Static(text, classes="system-message")
        conv.mount(msg)
        msg.scroll_visible()

    def _render_status_bar(self) -> str:
        """Render the compact status bar."""
        s = self.session
        parts = [
            f"[{Colors.DIM}]{s.repository or 'no project'}[/{Colors.DIM}]",
            f"[{Colors.DIM}]{s.branch or ''}[/{Colors.DIM}]",
        ]
        if s.current_job_id:
            parts.append(f"job: {s.current_job_id}")
        return "  │  ".join(parts)

    def action_cancel(self) -> None:
        """Handle Ctrl+C — clear input or offer to cancel job."""
        inp = self.query_one("#prompt-input", Input)
        if inp.value:
            inp.value = ""
        elif self.session.current_job_id:
            self._append_mya_message(
                f"¿Detener el job {self.session.current_job_id}?\n\n[A] Detener  [N] Continuar"
            )
        else:
            self._append_system_message(f"[{Colors.DIM}]Ctrl+D para salir.[/{Colors.DIM}]")

    def action_escape(self) -> None:
        """Handle Escape — clear input."""
        inp = self.query_one("#prompt-input", Input)
        inp.value = ""

    def action_open_projects(self) -> None:
        """Open the Project Explorer screen."""

        def on_return(_: Any = None) -> None:
            # Refresh header/status bar/welcome when returning from Project Explorer
            try:
                self.query_one("#welcome", WelcomePanel).refresh()
                self.query_one("#status-bar", Static).update(self._render_status_bar())
            except Exception:
                pass

        self.push_screen(ProjectsScreen(session=self.session), on_return)

    async def action_quit(self) -> None:
        """Handle Ctrl+D — exit."""
        self.exit()


def run(repo_path: str | None = None) -> None:
    """Entry point for the `mya` command."""
    path = Path(repo_path).resolve() if repo_path else None
    app = MyaApp(repo_path=path)
    app.run()


if __name__ == "__main__":
    run()
