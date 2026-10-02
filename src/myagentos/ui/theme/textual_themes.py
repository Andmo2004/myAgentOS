"""Textual (CSS-level) themes that mirror the presentation themes in themes.py.

The presentation ThemeRegistry drives Rich markup and symbols; these themes drive
widget backgrounds, borders, and focus states so both layers switch together.
"""

from typing import Final

from textual.theme import Theme as TextualTheme

from myagentos.ui.theme.mya_theme import INK, LINE, MUTED, PROVIDERS, build_theme

_COMMON_VARS = {
    "mya-muted": MUTED,
    "mya-line": LINE,
    "input-cursor-foreground": INK,
    "input-cursor-background": "#C9CED8",
    "input-selection-background": "#C9CED8 35%",
    **{f"p-{q.id}": q.primary for q in PROVIDERS.values()},
}

MYA_PROVIDER_THEMES: Final[tuple[TextualTheme, ...]] = tuple(
    build_theme(p) for p in PROVIDERS.values()
)

MYA_DARK: Final[TextualTheme] = build_theme(PROVIDERS["mya"])

MYA_MINIMAL: Final[TextualTheme] = TextualTheme(
    name="mya-minimal",
    primary="#C9CED8",
    secondary="#8B93A7",
    accent="#C9CED8",
    success="#86EFAC",
    warning="#FDE68A",
    error="#FCA5A5",
    foreground="#D4D8E0",
    background="#101114",
    surface="#16181D",
    panel="#1D2026",
    dark=True,
    variables=_COMMON_VARS,
)

MYA_HIGH_CONTRAST: Final[TextualTheme] = TextualTheme(
    name="mya-contrast",
    primary="#FFE14D",
    secondary="#5CF2FF",
    accent="#5CF2FF",
    success="#5CFF7A",
    warning="#FFE14D",
    error="#FF5C5C",
    foreground="#FFFFFF",
    background="#000000",
    surface="#0A0A0A",
    panel="#1A1A1A",
    dark=True,
    variables=_COMMON_VARS,
)

MYA_TEXTUAL_THEMES: Final[tuple[TextualTheme, ...]] = (
    *MYA_PROVIDER_THEMES,
    MYA_MINIMAL,
    MYA_HIGH_CONTRAST,
)

PRESENTATION_TO_TEXTUAL: Final[dict[str, str]] = {
    "default": "mya-mock",
    "minimal": MYA_MINIMAL.name,
    "high_contrast": MYA_HIGH_CONTRAST.name,
    "monochrome": "ansi-dark",
}
