"""Token meter widget displaying usage progress and cost tiers (§7.3, §8.1.C)."""

from typing import Any

from textual.widgets import Static

from myagentos.ui.theme.animation import render_progress_bar
from myagentos.ui.theme.symbols import (
    ASCII_COST_TIER_BADGES,
    COST_TIER_BADGES,
    CostTier,
)
from myagentos.ui.theme.themes import ThemeRegistry


class TokenMeterWidget(Static):
    """Visual meter for token budget consumption and cost scale."""

    def __init__(
        self,
        used_tokens: int = 0,
        budget_tokens: int = 50000,
        cost_usd: float = 0.0,
        cost_tier: CostTier = CostTier.LOW,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.used_tokens = used_tokens
        self.budget_tokens = max(1, budget_tokens)
        self.cost_usd = cost_usd
        self.cost_tier = cost_tier
        super().__init__(*args, **kwargs)

    def update_usage(
        self,
        used_tokens: int,
        budget_tokens: int,
        cost_usd: float,
        cost_tier: CostTier | None = None,
    ) -> None:
        self.used_tokens = used_tokens
        self.budget_tokens = max(1, budget_tokens)
        self.cost_usd = cost_usd
        if cost_tier is not None:
            self.cost_tier = cost_tier
        elif self.used_tokens < 20000:
            self.cost_tier = CostTier.LOW
        elif self.used_tokens < 40000:
            self.cost_tier = CostTier.MEDIUM
        elif self.used_tokens < 80000:
            self.cost_tier = CostTier.HIGH
        else:
            self.cost_tier = CostTier.VERY_HIGH
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        ratio = min(1.0, self.used_tokens / self.budget_tokens)
        bar = render_progress_bar(ratio, width=16, ascii_only=theme.ascii_only)
        badges = ASCII_COST_TIER_BADGES if theme.ascii_only else COST_TIER_BADGES
        tier_badge = badges.get(self.cost_tier, "[LOW]")

        return (
            f"[bold cyan]TOKENS & COST[/bold cyan]\n"
            f"  tokens: {self.used_tokens:,} / {self.budget_tokens:,}  {bar}\n"
            f"  tier:   {tier_badge}  [dim]spent:[/dim] [yellow]${self.cost_usd:.4f}[/yellow]"
        )
