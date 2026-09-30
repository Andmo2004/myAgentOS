"""Project Manager & Project Explorer screen for Mya TUI.

Provides the administrative view of projects:
- View active projects with visible tags, status, and path
- Switch active project for Mya session
- New project creation
- Add existing project
- Soft delete (Move to Trash)
- Restore from Trash
- Permanent delete from Trash with mandatory confirmation modal
- Absolute safety: repository files on disk are never deleted
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, Static

from myagentos.projects.models import Project, ProjectFilter
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session, detect_git_info
from myagentos.ui.themes import Colors


class ConfirmPermanentDeleteModal(ModalScreen[bool]):
    """Mandatory confirmation modal for permanent project registration deletion."""

    CSS = """
    ConfirmPermanentDeleteModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #confirm_dialog {
        width: 65;
        height: auto;
        border: thick red;
        background: $surface;
        padding: 1 2;
    }

    #confirm_buttons {
        margin-top: 1;
        align: right middle;
        height: auto;
    }

    #confirm_buttons Button {
        margin-left: 2;
    }
    """

    def __init__(self, project: Project, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.project = project

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_dialog"):
            yield Label(
                f"[bold red]Permanently delete registration for '{self.project.name}'?[/bold red]"
            )
            yield Static(
                "\nThis removes the project registration from Agentic OS and\n"
                "deletes its Mya project memory association.\n\n"
                "[bold]This action cannot be undone.[/bold]\n\n"
                f"[bold green]Repository files at '{self.project.path}' "
                "will NOT be deleted.[/bold green]"
            )
            with Horizontal(id="confirm_buttons"):
                yield Button("Cancel", id="btn_cancel", variant="default")
                yield Button("Delete Permanently", id="btn_confirm_delete", variant="error")

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#btn_confirm_delete")
    def on_confirm(self) -> None:
        self.dismiss(True)


class NewProjectModal(ModalScreen[dict[str, str] | None]):
    """Modal to create a new project."""

    CSS = """
    NewProjectModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #new_dialog {
        width: 60;
        height: auto;
        border: thick cyan;
        background: $surface;
        padding: 1 2;
    }

    #new_buttons {
        margin-top: 1;
        align: right middle;
        height: auto;
    }

    #new_buttons Button {
        margin-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="new_dialog"):
            yield Label("[bold cyan]Create New Project[/bold cyan]\n")
            yield Label("Project Name:")
            yield Input(placeholder="e.g. acme-backend", id="input_name")
            yield Label("\nDirectory Path (empty for current dir / name):")
            yield Input(placeholder="e.g. ~/projects/acme-backend", id="input_path")
            with Horizontal(id="new_buttons"):
                yield Button("Cancel", id="btn_new_cancel", variant="default")
                yield Button("Create", id="btn_new_submit", variant="primary")

    @on(Button.Pressed, "#btn_new_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_new_submit")
    def on_submit(self) -> None:
        name_input = self.query_one("#input_name", Input).value.strip()
        path_input = self.query_one("#input_path", Input).value.strip()
        if not name_input:
            return
        self.dismiss({"name": name_input, "path": path_input})


class AddProjectModal(ModalScreen[str | None]):
    """Modal to register an existing project directory."""

    CSS = """
    AddProjectModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #add_dialog {
        width: 60;
        height: auto;
        border: thick cyan;
        background: $surface;
        padding: 1 2;
    }

    #add_buttons {
        margin-top: 1;
        align: right middle;
        height: auto;
    }

    #add_buttons Button {
        margin-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="add_dialog"):
            yield Label("[bold cyan]Add Existing Project[/bold cyan]\n")
            yield Label("Repository Directory Path:")
            yield Input(placeholder="e.g. /path/to/my-repo or .", id="input_add_path")
            with Horizontal(id="add_buttons"):
                yield Button("Cancel", id="btn_add_cancel", variant="default")
                yield Button("Add Project", id="btn_add_submit", variant="primary")

    @on(Button.Pressed, "#btn_add_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_add_submit")
    def on_submit(self) -> None:
        path_input = self.query_one("#input_add_path", Input).value.strip()
        if not path_input:
            return
        self.dismiss(path_input)


class ProjectsScreen(Screen[None]):
    """Project Explorer screen."""

    BINDINGS = [
        Binding("escape", "dismiss_screen", "Back", show=True),
        Binding("q", "dismiss_screen", "Back", show=False),
        Binding("n", "new_project", "New Project", show=True),
        Binding("a", "add_project", "Add Project", show=True),
        Binding("t", "toggle_trash", "Toggle Trash", show=True),
        Binding("r", "refresh_list", "Refresh", show=True),
    ]

    CSS = """
    ProjectsScreen {
        layout: vertical;
        background: $background;
    }

    #top_bar {
        height: auto;
        padding: 1 2;
        background: $surface;
        border-bottom: heavy $primary;
    }

    #search_bar {
        margin: 1 2 0 2;
        height: auto;
    }

    #content_area {
        height: 1fr;
        padding: 1 2;
    }

    .project_card {
        border: round $primary;
        padding: 1 2;
        margin-bottom: 1;
        background: $surface;
        height: auto;
    }

    .project_card_trashed {
        border: round red;
        padding: 1 2;
        margin-bottom: 1;
        background: $surface;
        height: auto;
    }

    .card_buttons {
        margin-top: 1;
        height: auto;
    }

    .card_buttons Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        session: Session,
        service: ProjectManagerService | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.session = session
        self.service = service or ProjectManagerService()
        self.view_trash = False
        self.search_query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="top_bar"):
            yield Label(
                f"[bold {Colors.PRIMARY}]MYA · PROJECT EXPLORER[/bold {Colors.PRIMARY}]"
            )
            yield Label(
                f"[{Colors.DIM}][N] New Project  [A] Add Project  "
                f"[T] Toggle Trash  [R] Refresh  [Esc/Q] Back to Mya[/{Colors.DIM}]"
            )

        yield Input(
            placeholder="Search projects by name, path, or tag...",
            id="search_bar",
        )

        with VerticalScroll(id="content_area"):
            yield Static("Loading projects...", id="loading_placeholder")

    def on_mount(self) -> None:
        self.refresh_projects()

    def action_dismiss_screen(self) -> None:
        self.app.pop_screen()

    def action_new_project(self) -> None:
        def on_result(res: dict[str, str] | None) -> None:
            if res:
                name = res["name"]
                path = Path(res["path"]).resolve() if res["path"] else Path.cwd() / name
                try:
                    self.service.create_project(name=name, path=path)
                    self.refresh_projects()
                except Exception as exc:
                    self.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(NewProjectModal(), on_result)

    def action_add_project(self) -> None:
        def on_result(path_str: str | None) -> None:
            if path_str:
                path = Path(path_str).resolve()
                try:
                    self.service.add_project(path)
                    self.refresh_projects()
                except Exception as exc:
                    self.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(AddProjectModal(), on_result)

    def action_toggle_trash(self) -> None:
        self.view_trash = not self.view_trash
        self.refresh_projects()

    def action_refresh_list(self) -> None:
        self.refresh_projects()

    @on(Input.Changed, "#search_bar")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value.strip()
        self.refresh_projects()

    def refresh_projects(self) -> None:
        try:
            container = self.query_one("#content_area", VerticalScroll)
        except Exception:
            return

        container.remove_children()

        if self.view_trash:
            trashed = self.service.list_trash()
            if self.search_query:
                trashed = [
                    p
                    for p in trashed
                    if self.search_query.lower() in p.name.lower()
                    or self.search_query.lower() in p.path.lower()
                    or any(self.search_query.lower() in t.label.lower() for t in p.visible_tags)
                ]

            title_label = Static(
                f"[bold red]PROJECT TRASH ({len(trashed)})[/bold red] — "
                f"[{Colors.DIM}]Repositories on disk remain untouched.[/{Colors.DIM}]\n"
            )
            container.mount(title_label)

            if not trashed:
                container.mount(Static(f"[{Colors.DIM}]The Trash is empty.[/{Colors.DIM}]"))
                return

            for proj in trashed:
                tags = " ".join(f"[{t.label}]" for t in proj.visible_tags)
                trashed_str = (
                    proj.trashed_at.strftime("%Y-%m-%d %H:%M") if proj.trashed_at else "N/A"
                )
                elements: list[Any] = [Label(f"[bold red]● {proj.name}[/bold red]")]
                if tags:
                    elements.append(Label(f"  [magenta]{tags}[/magenta]"))
                elements.extend(
                    [
                        Label(f"  [dim]Path: {proj.path}[/dim]"),
                        Label(f"  [yellow]Trashed: {trashed_str}[/yellow]"),
                        Horizontal(
                            Button("Restore", variant="success", id=f"restore_{proj.project_id}"),
                            Button(
                                "Delete Permanently",
                                variant="error",
                                id=f"purge_{proj.project_id}",
                            ),
                            classes="card_buttons",
                        ),
                    ]
                )
                card = Vertical(*elements, classes="project_card_trashed")
                container.mount(card)

        else:
            projects = self.service.list_projects(
                filter_criteria=ProjectFilter(query=self.search_query or None)
            )
            title_label = Static(
                f"[bold cyan]ACTIVE PROJECTS ({len(projects)})[/bold cyan] — "
                f"[{Colors.DIM}]Select a project to switch Mya's context.[/{Colors.DIM}]\n"
            )
            container.mount(title_label)

            if not projects:
                container.mount(
                    Static(
                        f"[{Colors.DIM}]No projects found. "
                        f"Press 'N' to create or 'A' to add.[/{Colors.DIM}]"
                    )
                )
                return

            for proj in projects:
                tags = " ".join(f"[{t.label}]" for t in proj.visible_tags)
                git_str = f"Branch: {proj.branch or 'N/A'}"
                if proj.commit_short:
                    git_str += f" ({proj.commit_short})"
                is_current = (
                    self.session.project_id == proj.project_id
                    or str(self.session.repo_root) == proj.path
                )

                status_color = "green" if proj.state.value == "active" else "yellow"
                active_badge = " [bold green]◄ CURRENT[/bold green]" if is_current else ""
                elements = [
                    Label(
                        f"[bold {status_color}]● {proj.name}[/bold {status_color}]{active_badge}"
                    )
                ]
                if tags:
                    elements.append(Label(f"  [magenta]{tags}[/magenta]"))
                elements.extend(
                    [
                        Label(f"  [dim]Path: {proj.path}[/dim]"),
                        Label(f"  [yellow]{git_str}[/yellow] · [cyan]Mya ready[/cyan]"),
                        Horizontal(
                            Button(
                                "Open in Mya",
                                variant="primary",
                                id=f"open_{proj.project_id}",
                            ),
                            Button(
                                "Move to Trash",
                                variant="default",
                                id=f"trash_{proj.project_id}",
                            ),
                            classes="card_buttons",
                        ),
                    ]
                )
                card = Vertical(*elements, classes="project_card")
                container.mount(card)

    @on(Button.Pressed)
    def on_card_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("open_"):
            proj_id = button_id[len("open_") :]
            self._select_project(proj_id)
        elif button_id.startswith("trash_"):
            proj_id = button_id[len("trash_") :]
            self._trash_project(proj_id)
        elif button_id.startswith("restore_"):
            proj_id = button_id[len("restore_") :]
            self._restore_project(proj_id)
        elif button_id.startswith("purge_"):
            proj_id = button_id[len("purge_") :]
            self._purge_project(proj_id)

    def _select_project(self, project_id: str) -> None:
        proj = self.service.get_project(project_id)
        if not proj:
            self.notify("Project not found", severity="error")
            return

        self.session.project_id = proj.project_id
        self.session.repository = proj.name
        self.session.repo_root = Path(proj.path)
        self.session.branch = proj.branch or ""
        self.session.commit_short = proj.commit_short or ""
        self.session.project_profile = proj.profile

        # Re-detect git state if directory exists
        if Path(proj.path).exists():
            git = detect_git_info(Path(proj.path))
            if git:
                self.session.working_tree_clean = git.clean
                self.session.commit = git.commit
                self.session.commit_short = git.commit_short
                self.session.branch = git.branch

        self.notify(f"Switched active project to '{proj.name}'", severity="information")
        self.app.pop_screen()

    def _trash_project(self, project_id: str) -> None:
        try:
            proj = self.service.move_to_trash(project_id)
            self.notify(f"Moved '{proj.name}' to Trash", severity="warning")
            self.refresh_projects()
        except Exception as exc:
            self.notify(f"Failed moving to trash: {exc}", severity="error")

    def _restore_project(self, project_id: str) -> None:
        try:
            proj = self.service.restore_project(project_id)
            self.notify(f"Restored '{proj.name}' to active projects", severity="information")
            self.refresh_projects()
        except Exception as exc:
            self.notify(f"Failed restoring project: {exc}", severity="error")

    def _purge_project(self, project_id: str) -> None:
        proj = self.service.get_project(project_id)
        if not proj:
            return

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                try:
                    self.service.delete_permanently(project_id, confirm=True)
                    self.notify(
                        f"Permanently deleted registration for '{proj.name}'",
                        severity="error",
                    )
                    self.refresh_projects()
                except Exception as exc:
                    self.notify(f"Purge failed: {exc}", severity="error")

        self.app.push_screen(ConfirmPermanentDeleteModal(proj), on_confirm)
