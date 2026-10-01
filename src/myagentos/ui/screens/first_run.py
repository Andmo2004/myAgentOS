"""First-run onboarding wizard screen for Mya TUI (§5-§8, §13, §15, §16, §17).

Provides the 3-step initial setup sequence:
1. User display name preference
2. Visual theme selection with live preview
3. Mya Home storage location selection and directory initialization
Followed by a review & confirmation screen.
"""

from __future__ import annotations

import getpass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from myagentos.config.loader import save_config
from myagentos.config.paths import DEFAULT_MYA_HOME
from myagentos.setup.initializer import initialize_mya_home
from myagentos.setup.models import (
    MyaHomeConfig,
    SetupConfig,
    SetupMeta,
    UIConfig,
    UserConfig,
)
from myagentos.setup.validator import validate_mya_home
from myagentos.ui.theme.themes import ThemeRegistry


class FirstRunScreen(Screen[SetupConfig | None]):
    """Modal/Screen running the 3-question onboarding wizard."""

    BINDINGS = [
        Binding("escape", "dismiss_wizard", "Cancel", show=False),
    ]

    CSS = """
    FirstRunScreen {
        align: center middle;
        background: #0d1117;
    }

    #wizard_box {
        width: 74;
        height: auto;
        min-height: 24;
        max-height: 38;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    .brand_header {
        text-style: bold;
        color: $accent;
        text-align: center;
        margin-bottom: 1;
    }

    .step_number {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }

    .step_question {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    .step_desc {
        color: $text-muted;
        margin-bottom: 1;
    }

    .error_label {
        color: red;
        text-style: bold;
        margin-top: 1;
    }

    .preview_container {
        border: solid $accent;
        background: $panel;
        padding: 1;
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
    }

    .button_row {
        margin-top: 1;
        align: right middle;
        height: auto;
    }

    .button_row Button {
        margin-left: 2;
    }

    #radioset_theme {
        background: transparent;
        border: none;
        margin-bottom: 1;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Setup state
        self._current_step: int = 1
        default_user = ""
        try:
            default_user = getpass.getuser()
        except Exception:
            default_user = "Developer"

        self._chosen_name: str = default_user.capitalize()
        self._chosen_theme: str = "default"
        self._chosen_mya_home: Path = DEFAULT_MYA_HOME

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard_box"):
            yield Label("● Mya  |  Agentic OS", id="brand_title", classes="brand_header")

            # --- STEP 1: User display name ---
            with Vertical(id="step_1_container"):
                welcome_intro = "Welcome.\nAntes de empezar necesito configurar tres cosas."
                yield Label(welcome_intro, classes="step_desc")
                yield Label("1 / 3", classes="step_number")
                yield Label("¿Cómo quieres que te llame?", classes="step_question")
                yield Input(
                    value=self._chosen_name,
                    placeholder="Tu nombre o alias...",
                    id="input_display_name",
                )
                with Horizontal(classes="button_row"):
                    yield Button("Continuar", id="btn_step1_next", variant="primary")

            # --- STEP 2: Theme selection ---
            with Vertical(id="step_2_container"):
                yield Label("2 / 3", classes="step_number")
                yield Label("¿Qué tema quieres utilizar en la interfaz?", classes="step_question")
                with RadioSet(id="radioset_theme"):
                    yield RadioButton("Dark (default)", id="theme_default", value=True)
                    yield RadioButton("Minimal", id="theme_minimal")
                    yield RadioButton("High Contrast", id="theme_high_contrast")
                    yield RadioButton("Monochrome", id="theme_monochrome")

                yield Label("Preview:", classes="step_desc")
                with Container(classes="preview_container"):
                    yield Static(id="preview_theme_static")

                with Horizontal(classes="button_row"):
                    yield Button("Atrás", id="btn_step2_back", variant="default")
                    yield Button("Continuar", id="btn_step2_next", variant="primary")

            # --- STEP 3: Mya Home ---
            with Vertical(id="step_3_container"):
                yield Label("3 / 3", classes="step_number")
                yield Label("¿Dónde quieres que Mya esté alojada?", classes="step_question")
                home_desc = (
                    "Mya necesita un espacio propio para su configuración, sesiones, "
                    "memoria y estado local.\n(No es la carpeta de tu proyecto.)"
                )
                yield Label(home_desc, classes="step_desc")
                yield Label("Ubicación de Mya Home:", classes="step_desc")
                yield Input(
                    value=str(DEFAULT_MYA_HOME),
                    id="input_mya_home",
                )
                with Horizontal(classes="button_row"):
                    yield Button("Usar default", id="btn_use_default", variant="default")

                yield Label("", id="label_home_error", classes="error_label")

                with Horizontal(classes="button_row"):
                    yield Button("Atrás", id="btn_step3_back", variant="default")
                    yield Button("Continuar", id="btn_step3_next", variant="primary")

            # --- REVIEW & CONFIRM ---
            with Vertical(id="step_review_container"):
                yield Label("¡Listo! Aquí está tu configuración inicial:", classes="step_question")
                yield Static(id="static_review_details", classes="step_desc")
                yield Label("", id="label_review_error", classes="error_label")
                with Horizontal(classes="button_row"):
                    yield Button("Atrás", id="btn_review_back", variant="default")
                    yield Button("Confirmar y empezar", id="btn_confirm_setup", variant="success")

    def on_mount(self) -> None:
        """Initialize step visibility and preview."""
        self._update_theme_preview("default")
        self._show_step(1)

    def _show_step(self, step: int) -> None:
        self._current_step = step
        s1 = self.query_one("#step_1_container", Vertical)
        s2 = self.query_one("#step_2_container", Vertical)
        s3 = self.query_one("#step_3_container", Vertical)
        sr = self.query_one("#step_review_container", Vertical)

        s1.display = step == 1
        s2.display = step == 2
        s3.display = step == 3
        sr.display = step == 4

        if step == 1:
            self.query_one("#input_display_name", Input).focus()
        elif step == 2:
            self.query_one("#radioset_theme", RadioSet).focus()
            self._update_theme_preview(self._chosen_theme)
        elif step == 3:
            self.query_one("#input_mya_home", Input).focus()
        elif step == 4:
            self._update_review_summary()
            self.query_one("#btn_confirm_setup", Button).focus()

    def _update_theme_preview(self, theme_name: str) -> None:
        registry = ThemeRegistry.get_instance()
        theme = registry.get_theme(theme_name) or registry.active_theme
        primary = theme.colors.get("primary", "cyan")
        success = theme.colors.get("success", "green")
        accent = theme.colors.get("accent", "magenta")
        border = theme.colors.get("border", "cyan")

        preview_markup = (
            f"[{border}]┌────────────────────────────────────────────────────────┐[/]\n"
            f"[{border}]│[/] [{accent}]● Mya[/]   [{success}]✓ READY[/]   "
            f"[{primary}]Theme: {theme.name}[/]                   [{border}]│[/]\n"
            f"[{border}]│[/] Repository: [bold]example-project[/]  Branch: [bold]main[/]          "
            f"[{border}]│[/]\n"
            f"[{border}]└────────────────────────────────────────────────────────┘[/]"
        )
        self.query_one("#preview_theme_static", Static).update(preview_markup)

    def _update_review_summary(self) -> None:
        summary_text = (
            f"\n[bold]Nombre preferido:[/]  {self._chosen_name}\n\n"
            f"[bold]Tema visual:[/]       {self._chosen_theme}\n\n"
            f"[bold]Mya Home:[/]          {self._chosen_mya_home}\n"
        )
        self.query_one("#static_review_details", Static).update(summary_text)

    # --- Step 1 Actions ---
    @on(Input.Submitted, "#input_display_name")
    def on_display_name_submitted(self) -> None:
        self._advance_from_step1()

    @on(Button.Pressed, "#btn_step1_next")
    def on_step1_next(self) -> None:
        self._advance_from_step1()

    def _advance_from_step1(self) -> None:
        raw_name = self.query_one("#input_display_name", Input).value.strip()
        self._chosen_name = raw_name if raw_name else "Developer"
        self._show_step(2)

    # --- Step 2 Actions ---
    @on(RadioSet.Changed, "#radioset_theme")
    def on_theme_changed(self, event: RadioSet.Changed) -> None:
        selected_btn = event.pressed
        if not selected_btn:
            return
        if selected_btn.id == "theme_default":
            self._chosen_theme = "default"
        elif selected_btn.id == "theme_minimal":
            self._chosen_theme = "minimal"
        elif selected_btn.id == "theme_high_contrast":
            self._chosen_theme = "high_contrast"
        elif selected_btn.id == "theme_monochrome":
            self._chosen_theme = "monochrome"

        self._update_theme_preview(self._chosen_theme)

    @on(Button.Pressed, "#btn_step2_back")
    def on_step2_back(self) -> None:
        self._show_step(1)

    @on(Button.Pressed, "#btn_step2_next")
    def on_step2_next(self) -> None:
        self._show_step(3)

    # --- Step 3 Actions ---
    @on(Button.Pressed, "#btn_use_default")
    def on_use_default_clicked(self) -> None:
        self.query_one("#input_mya_home", Input).value = str(DEFAULT_MYA_HOME)
        self.query_one("#label_home_error", Label).update("")

    @on(Input.Submitted, "#input_mya_home")
    def on_mya_home_submitted(self) -> None:
        self._advance_from_step3()

    @on(Button.Pressed, "#btn_step3_back")
    def on_step3_back(self) -> None:
        self._show_step(2)

    @on(Button.Pressed, "#btn_step3_next")
    def on_step3_next(self) -> None:
        self._advance_from_step3()

    def _advance_from_step3(self) -> None:
        raw_home = self.query_one("#input_mya_home", Input).value.strip()
        val_res = validate_mya_home(raw_home)
        if not val_res.valid:
            self.query_one("#label_home_error", Label).update(f"Error: {val_res.error}")
            return

        self.query_one("#label_home_error", Label).update("")
        self._chosen_mya_home = val_res.resolved_path or Path(raw_home)
        self._show_step(4)

    # --- Review & Confirmation ---
    @on(Button.Pressed, "#btn_review_back")
    def on_review_back(self) -> None:
        self._show_step(3)

    @on(Button.Pressed, "#btn_confirm_setup")
    def on_confirm_setup(self) -> None:
        # Validate again before writing
        val_res = validate_mya_home(self._chosen_mya_home)
        if not val_res.valid:
            self.query_one("#label_review_error", Label).update(f"Error: {val_res.error}")
            return

        target_home = val_res.resolved_path or self._chosen_mya_home

        try:
            # 1. Initialize directory structure
            initialize_mya_home(target_home)

            # 2. Build configuration
            config = SetupConfig(
                schema_version=1,
                setup=SetupMeta(
                    completed=True,
                    completed_at=datetime.now(UTC).isoformat(),
                    version=1,
                ),
                user=UserConfig(display_name=self._chosen_name),
                ui=UIConfig(theme=self._chosen_theme, motion="full"),
                mya=MyaHomeConfig(home=str(target_home)),
            )

            # 3. Save settings.yaml
            save_config(config, mya_home=target_home)

            # 4. Dismiss screen with the completed config
            self.dismiss(config)
        except Exception as exc:
            err_msg = f"Error initializing Mya Home: {exc}"
            self.query_one("#label_review_error", Label).update(err_msg)

    def action_dismiss_wizard(self) -> None:
        self.dismiss(None)
