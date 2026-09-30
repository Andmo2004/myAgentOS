"""Theme system and catalog for Agentic OS interactive UI (§20).

Supports default, minimal, high_contrast, and monochrome themes.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from myagentos.ui.theme.symbols import (
    ASCII_SYMBOLS,
    UNICODE_SYMBOLS,
    VisualStatus,
)


class Theme(BaseModel):
    """Configuration for a visual theme (§20)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    colors: dict[str, str] = Field(default_factory=dict)
    symbols: dict[str, str] = Field(default_factory=dict)
    density: str = "comfortable"  # "comfortable" | "compact"
    ascii_only: bool = False

    def get_symbol(self, status: VisualStatus | str) -> str:
        """Resolves symbol for status within this theme."""
        key = status.value if isinstance(status, VisualStatus) else str(status).lower()
        if key in self.symbols:
            return self.symbols[key]
        if self.ascii_only:
            try:
                return ASCII_SYMBOLS[VisualStatus(key)]
            except (ValueError, KeyError):
                return "?"
        try:
            return UNICODE_SYMBOLS[VisualStatus(key)]
        except (ValueError, KeyError):
            return "•"

    def color(self, token: str, fallback: str = "white") -> str:
        """Resolves color code for token."""
        return self.colors.get(token, fallback)


DEFAULT_COLORS: Final[dict[str, str]] = {
    "primary": "cyan",
    "secondary": "blue",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "dim": "dim white",
    "accent": "magenta",
    "info": "bright_blue",
    "border": "cyan",
    "header": "bold cyan",
}

MINIMAL_COLORS: Final[dict[str, str]] = {
    "primary": "white",
    "secondary": "dim white",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "dim": "dim",
    "accent": "cyan",
    "info": "white",
    "border": "dim",
    "header": "bold white",
}

HIGH_CONTRAST_COLORS: Final[dict[str, str]] = {
    "primary": "bold bright_yellow",
    "secondary": "bold bright_cyan",
    "success": "bold bright_green",
    "warning": "bold bright_yellow",
    "error": "bold bright_red",
    "dim": "white",
    "accent": "bold bright_magenta",
    "info": "bold bright_cyan",
    "border": "bright_white",
    "header": "bold bright_yellow",
}

MONOCHROME_COLORS: Final[dict[str, str]] = {
    "primary": "white",
    "secondary": "white",
    "success": "white",
    "warning": "white",
    "error": "white",
    "dim": "dim",
    "accent": "white",
    "info": "white",
    "border": "white",
    "header": "bold white",
}

DEFAULT_THEME: Final[Theme] = Theme(
    name="default",
    description="Modern dark palette with curated cyan/blue/green/magenta accents.",
    colors=DEFAULT_COLORS,
    density="comfortable",
    ascii_only=False,
)

MINIMAL_THEME: Final[Theme] = Theme(
    name="minimal",
    description="Clean, understated palette with muted borders and minimal visual noise.",
    colors=MINIMAL_COLORS,
    density="compact",
    ascii_only=False,
)

HIGH_CONTRAST_THEME: Final[Theme] = Theme(
    name="high_contrast",
    description="High-visibility palette with stark contrast for maximum legibility.",
    colors=HIGH_CONTRAST_COLORS,
    density="comfortable",
    ascii_only=False,
)

MONOCHROME_THEME: Final[Theme] = Theme(
    name="monochrome",
    description="Zero-color fallback theme with strict ASCII symbols for limited terminals.",
    colors=MONOCHROME_COLORS,
    density="comfortable",
    ascii_only=True,
)


class ThemeRegistry:
    """Manages active theme and catalog of available themes."""

    _instance: "ThemeRegistry | None" = None

    def __init__(self) -> None:
        self._themes: dict[str, Theme] = {
            DEFAULT_THEME.name: DEFAULT_THEME,
            MINIMAL_THEME.name: MINIMAL_THEME,
            HIGH_CONTRAST_THEME.name: HIGH_CONTRAST_THEME,
            MONOCHROME_THEME.name: MONOCHROME_THEME,
        }
        self._active: Theme = DEFAULT_THEME

    @classmethod
    def get_instance(cls) -> "ThemeRegistry":
        if cls._instance is None:
            cls._instance = ThemeRegistry()
        return cls._instance

    @property
    def active_theme(self) -> Theme:
        return self._active

    def set_active_theme(self, name: str) -> Theme:
        clean = name.strip().lower()
        if clean not in self._themes:
            raise ValueError(
                f"Theme '{name}' not found. Available: {', '.join(sorted(self._themes.keys()))}"
            )
        self._active = self._themes[clean]
        return self._active

    def get_theme(self, name: str) -> Theme | None:
        return self._themes.get(name.strip().lower())

    def list_themes(self) -> list[Theme]:
        return list(self._themes.values())

    def register_theme(self, theme: Theme) -> None:
        self._themes[theme.name.lower()] = theme
