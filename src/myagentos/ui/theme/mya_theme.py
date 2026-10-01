"""Identidad visual de Mya: paleta TrueColor, estilo por proveedor, wordmark con degradado,
bienvenida accionable, indicador de "pensando" y barra de estado segmentada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as RichTheme
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import Static

REDUCED_MOTION = bool(os.environ.get("MYA_REDUCED_MOTION"))

# --- Paleta base TrueColor (común a todos los proveedores) -------------------
INK = "#15131F"      # Fondo principal
SURFACE = "#1D1A2B"  # Bloques secundarios y fondos inactivos
PANEL = "#2A2640"    # Segmentos activos de la barra y paneles
LINE = "#3A3556"     # Separadores, bordes tenues
MUTED = "#8E89A8"    # Texto secundario
TEXT = "#E8E3F2"     # Texto principal
SAND = "#EDC987"     # Pendiente / aviso / mensajes del usuario
SAGE = "#8CC7A1"     # Correcto (siempre con ✓)
RED = "#F2635A"      # Error


# --- Proveedores -------------------------------------------------------------
@dataclass(frozen=True)
class ProviderStyle:
    id: str
    label: str
    primary: str                     # Color principal del tema
    gradient: tuple[str, str]        # Degradado del wordmark: izquierda → derecha
    glyph: str                       # Glifo firma: barra de estado y avisos
    spinner: tuple[str, ...]         # Frames del indicador "pensando"
    phrases: tuple[str, ...]         # Frases que rotan mientras piensa


PROVIDERS: dict[str, ProviderStyle] = {p.id: p for p in (
    ProviderStyle(
        "mya", "Mya", "#D97BB6", (SAND, "#D97BB6"), "◆",
        tuple("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"), ("trabajando",),
    ),
    ProviderStyle(
        "mock", "Mock", "#45C8DC", ("#B8F2F7", "#38BDD8"), "◇",
        tuple("▁▂▃▄▅▆▇█▇▆▅▄▃▂"), ("simulando respuesta", "generando datos de prueba"),
    ),
    ProviderStyle(
        "claude", "Claude", "#E2804F", ("#F2B880", "#E2804F"), "✺",
        tuple("◜◠◝◞◡◟"), ("pensando", "dándole vueltas", "ordenando ideas"),
    ),
    ProviderStyle(
        "openai", "OpenAI", "#10A37F", ("#8FE3C8", "#10A37F"), "◉",
        tuple("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"), ("razonando", "analizando", "componiendo"),
    ),
    ProviderStyle(
        "gemini", "Gemini", "#5B9DF9", ("#5B9DF9", "#A78BFA"), "✦",
        tuple("✦✧✦✧"), ("explorando", "conectando ideas", "sintetizando"),
    ),
)}

_VENDOR_ALIASES = {"anthropic": "claude", "google": "gemini", "openai": "openai"}
_PREFIXES = (
    ("claude", "claude"), ("gpt", "openai"), ("chatgpt", "openai"),
    ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
    ("gemini", "gemini"), ("mock", "mock"),
)


def resolve_provider(model_id: str, provider: str | None = None) -> str:
    """Devuelve el id de proveedor para un modelo.

    Orden:
    1) `provider` explícito de la config.
    2) Vendor en ids tipo "anthropic/claude-…".
    3) Prefijo del id.
    4) "mya" (genérico de respaldo).
    """
    if provider:
        p = _VENDOR_ALIASES.get(provider.lower().strip(), provider.lower().strip())
        if p in PROVIDERS:
            return p
    mid = model_id.lower().strip()
    if "/" in mid:
        vendor, mid = mid.split("/", 1)
        if vendor in _VENDOR_ALIASES:
            return _VENDOR_ALIASES[vendor]
        if vendor in PROVIDERS:
            return vendor
    for prefix, pid in _PREFIXES:
        if mid.startswith(prefix):
            return pid
    return "mya"


def build_theme(p: ProviderStyle) -> Theme:
    return Theme(
        name=f"mya-{p.id}",
        primary=p.primary,
        secondary=SAND,
        accent=SAND,
        success=SAGE,
        warning=SAND,
        error=RED,
        foreground=TEXT,
        background=INK,
        surface=SURFACE,
        panel=PANEL,
        dark=True,
        variables={
            "mya-muted": MUTED,
            "mya-line": LINE,
            "input-cursor-foreground": INK,
            "input-cursor-background": p.primary,
            "input-selection-background": f"{p.primary} 35%",
            # Todos los colores de proveedor disponibles en cualquier tema:
            # permite que cada mensaje conserve el color del modelo que lo generó.
            **{f"p-{q.id}": q.primary for q in PROVIDERS.values()},
        },
    )


def register_all_themes(app: Any) -> None:
    for p in PROVIDERS.values():
        app.register_theme(build_theme(p))


# Markdown de las respuestas: independiente del proveedor, para que el
# historial no cambie de color al cambiar de modelo.
MYA_RICH_THEME = RichTheme({
    "markdown.code": f"bold {SAND}",
    "markdown.code_block": TEXT,
    "markdown.link": f"underline {TEXT}",
    "markdown.link_url": MUTED,
    "markdown.item.bullet": MUTED,
    "markdown.item.number": MUTED,
    "markdown.h1": f"bold {TEXT}",
    "markdown.h2": f"bold {TEXT}",
    "markdown.h3": f"bold {TEXT}",
    "markdown.block_quote": MUTED,
    "markdown.hr": LINE,
})


def current_style(widget: Any) -> ProviderStyle:
    try:
        app = getattr(widget, "app", None)
    except Exception:
        app = None
    provider_id = getattr(app, "provider", "mya") if app else "mya"
    return PROVIDERS.get(provider_id, PROVIDERS["mya"])


# --- Color -------------------------------------------------------------------
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lerp(a: str, b: str, t: float) -> str:
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    t = max(0.0, min(1.0, t))
    return "#{:02X}{:02X}{:02X}".format(
        round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t), round(b1 + (b2 - b1) * t)
    )


# --- Wordmark ----------------------------------------------------------------
WORDMARK = (
    "█▀▄▀█  ▀▄▀  ▄▀█",
    "█ ▀ █   █   █▀█",
)


def wordmark(progress: float = 1.0, gradient: tuple[str, str] = (SAND, "#D97BB6")) -> list[Text]:
    """Líneas del logo con degradado. `progress` (0..1) lo revela de izquierda a derecha."""
    width = max(len(line) for line in WORDMARK)
    edge = progress * (width + 3)
    out: list[Text] = []
    for line in WORDMARK:
        t = Text()
        for col, ch in enumerate(line):
            if ch == " ":
                t.append(" ")
            elif col > edge:
                t.append(ch, style=LINE)  # aún sin revelar
            else:
                t.append(ch, style=f"bold {lerp(*gradient, col / (width - 1))}")
        out.append(t)
    return out


class WelcomeGroup(Group):
    """Rich Group wrapper for Welcome renderables preserving string summary for tests."""

    def __init__(self, *renderables: Any, user: str = "", model_id: str = "") -> None:
        super().__init__(*renderables)
        self.user = user
        self.model_id = model_id

    def __str__(self) -> str:
        greeting = f"Hola, {self.user}." if self.user else "Hola."
        return f"{greeting} {self.model_id}"


# --- Bienvenida --------------------------------------------------------------
class Welcome(Static):
    """Cabecera compacta y accionable. Solo muestra lo que falta por hacer."""

    progress = reactive(0.0, init=False)

    class ActionRequested(Message):
        def __init__(self, text: str, submit: bool = True) -> None:
            super().__init__()
            self.text = text
            self.submit = submit

    def __init__(
        self,
        user_or_session: Any = "",
        *,
        has_model: bool | None = None,
        has_project: bool | None = None,
        session: Any = None,
        model_id: str = "mock-mya",
        user_name: str = "",
        version: str = "0.1",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if isinstance(user_or_session, str):
            self.user = user_or_session or user_name
            self.session = session
        else:
            self.session = user_or_session or session
            self.user = user_name

        if not self.user:
            import getpass

            try:
                self.user = getpass.getuser().capitalize()
            except Exception:
                self.user = "Andmo"

        self.version = version
        self._model_id = model_id

        if has_model is not None:
            self.has_model = has_model
        else:
            self.has_model = model_id not in ("mock-mya", "mock", "", None)

        if has_project is not None:
            self.has_project = has_project
        elif self.session and getattr(self.session, "repository", None):
            self.has_project = bool(self.session.repository)
        else:
            self.has_project = False

    @property
    def user_name(self) -> str:
        return self.user

    @user_name.setter
    def user_name(self, value: str) -> None:
        self.user = value
        self._paint()

    @property
    def model_id(self) -> str:
        return self._model_id

    @model_id.setter
    def model_id(self, value: str) -> None:
        self._model_id = value
        self.has_model = value not in ("mock-mya", "mock", "", None)
        self._paint()

    def _build_renderable(self) -> WelcomeGroup:
        logo = wordmark(self.progress, current_style(self).gradient)
        logo[-1].append(f"   agentic os {self.version}", style=MUTED)

        todo: list[tuple[str, str]] = []
        if not self.has_model:
            todo.append(("/key", "conectar un modelo"))
        if not self.has_project:
            todo.append(("/projects", "abrir un proyecto"))

        tail = (
            ". Aún falta preparar el entorno."
            if todo
            else ". Cuéntame qué quieres construir o arreglar."
        )
        if self.user:
            msg = Text.assemble(("Hola, ", TEXT), (self.user, f"bold {TEXT}"), (tail, TEXT))
        else:
            msg = Text.assemble(("Hola", f"bold {TEXT}"), (tail, TEXT))

        hints = Table.grid(padding=(0, 2))
        hints.add_column()
        hints.add_column()
        for cmd, desc in todo:  # pendiente → arena
            hints.add_row(
                Text.assemble(("│ ", SAND), (cmd, f"bold {SAND}")),
                Text(desc, style=TEXT),
            )
        for cmd, desc in (
            ("ctrl+p", "paleta de comandos"),
            ("/help", "todos los comandos"),
        ):
            hints.add_row(
                Text.assemble(("  ", MUTED), (cmd, MUTED)),
                Text(desc, style=MUTED),
            )

        return WelcomeGroup(
            *logo,
            Text(""),
            msg,
            Text(""),
            hints,
            user=self.user,
            model_id=self._model_id,
        )

    def render(self) -> WelcomeGroup:
        return self._build_renderable()

    def on_mount(self) -> None:
        self.watch(self.app, "provider", self._on_provider, init=False)
        self._reveal()

    def _reveal(self) -> None:
        if REDUCED_MOTION or os.environ.get("MYA_REDUCED_MOTION"):
            self.progress = 1.0
            self._paint()
            return
        self.progress = 0.0
        self._paint()
        self.animate("progress", 1.0, duration=0.6, easing="out_cubic")

    def _on_provider(self, _new: str) -> None:
        self._reveal()

    def watch_progress(self) -> None:
        self._paint()

    def refresh_info(self) -> None:
        if self.session and getattr(self.session, "repository", None):
            self.has_project = bool(self.session.repository)
        self.has_model = self.model_id not in ("mock-mya", "mock", "", None)
        self._paint()

    def _paint(self) -> None:
        self.update(self._build_renderable())


# Alias de compatibilidad
WelcomePanel = Welcome


# --- Indicador "pensando" ----------------------------------------------------
class Thinking(Static):
    """Spinner y frases propios del proveedor activo."""

    def __init__(
        self,
        label: str | None = None,
        animate: bool = True,
        ascii_only: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__("", **kwargs)
        self._custom_label = label
        self._animate = animate
        self._ascii_only = ascii_only
        self._i = 0

    def on_mount(self) -> None:
        self._i = 0
        self._paint()
        if self._animate and not REDUCED_MOTION and not os.environ.get("MYA_REDUCED_MOTION"):
            self.set_interval(0.09, self._tick)

    def _tick(self) -> None:
        self._i += 1
        self._paint()

    def _paint(self) -> None:
        s = current_style(self)
        is_reduced = bool(REDUCED_MOTION or os.environ.get("MYA_REDUCED_MOTION") or not self._animate)
        frame = s.glyph if is_reduced else s.spinner[self._i % len(s.spinner)]
        if self._custom_label:
            phrase = self._custom_label
        else:
            phrase = s.phrases[(self._i // 28) % len(s.phrases)]
        self.update(Text.assemble((f"{frame} ", f"bold {s.primary}"), (f"{phrase}…", MUTED)))


# Alias de compatibilidad
ThinkingIndicator = Thinking


# --- Barra de estado segmentada ----------------------------------------------
class StatusLine(Horizontal):
    """Segmentos con fondo. Los que no tienen valor simplemente no se pintan."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._project: str | None = None
        self._branch: str | None = None
        self._model: str | None = None
        self._job: str | None = None
        self._dirty: bool = False

    def compose(self) -> ComposeResult:
        yield Static(id="status-left")
        yield Static(id="status-right")

    def on_mount(self) -> None:
        self.watch(self.app, "provider", lambda _p: self._paint(), init=False)
        try:
            self.query_one("#status-right", Static).update(
                Text.assemble(
                    ("ctrl+p", f"bold {TEXT}"),
                    (" paleta", MUTED),
                )
            )
        except Exception:
            pass
        self._paint()

    def set(
        self,
        *,
        project: str | None = None,
        branch: str | None = None,
        model: str | None = None,
        job: str | None = None,
        dirty: bool = False,
    ) -> None:
        self._project = project or None
        self._branch = branch or None
        self._model = model or None
        self._job = job or None
        self._dirty = dirty
        self._paint()

    def update(self, _content: Any = None) -> None:
        self._paint()

    def _paint(self) -> None:
        s = current_style(self)
        bar = Text()
        bar.append(f" {s.glyph} mya ", style=f"bold {INK} on {s.primary}")
        bar.append(" ")
        if self._project:
            bar.append(f" {self._project} ", style=f"{TEXT} on {PANEL}")
        else:
            bar.append(" sin proyecto ", style=f"{MUTED} on {SURFACE}")
        if self._branch:
            bar.append(" ")
            branch_label = f" ⎇ {self._branch}{' ●' if self._dirty else ''} "
            bar.append(branch_label, style=f"{SAGE} on {SURFACE}")
        if self._model:
            bar.append(" ")
            # El modelo simulado es un aviso, no un estado normal → arena
            is_mock = s.id == "mock" or (self._model and "mock" in self._model.lower())
            fg = SAND if is_mock else TEXT
            bar.append(f" {self._model} ", style=f"{fg} on {SURFACE}")
        if self._job:
            bar.append(" ")
            bar.append(f" job {self._job} ", style=f"{SAND} on {SURFACE}")
        try:
            self.query_one("#status-left", Static).update(bar)
            self.query_one("#status-right", Static).update(
                Text.assemble(
                    ("ctrl+p", f"bold {TEXT}"),
                    (" paleta", MUTED),
                )
            )
        except Exception:
            pass


# --- Bloque de mensaje de conversación ---------------------------------------
class MessageBlock(Static):
    """Bloque de mensaje con barra lateral que codifica quién habla."""

    def __init__(
        self,
        role: str,
        content: Any,
        provider: str | None = None,
        **kwargs: Any,
    ) -> None:
        css_role = "agent" if role in ("agent", "mya") else role
        classes = (
            f"chat-message -{css_role} {css_role} p-{provider}"
            if provider
            else f"chat-message -{css_role} {css_role}"
        )
        if "classes" in kwargs:
            classes = f"{classes} {kwargs.pop('classes')}"
        super().__init__(content, classes=classes, **kwargs)
        self.role = role
        self.provider = provider


# Alias de compatibilidad
ChatMessage = MessageBlock
