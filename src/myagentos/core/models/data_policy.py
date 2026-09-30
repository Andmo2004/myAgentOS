"""Data classification and trust tagging according to §18 and §19."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


class DataClassification(StrEnum):
    """Deterministic data classification (§18.1)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"

    @property
    def rank(self) -> int:
        ranks = {
            DataClassification.PUBLIC: 1,
            DataClassification.INTERNAL: 2,
            DataClassification.CONFIDENTIAL: 3,
            DataClassification.SECRET: 4,
        }
        return ranks[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, DataClassification):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, DataClassification):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, DataClassification):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, DataClassification):
            return self.rank >= other.rank
        return NotImplemented

    def combine_with(self, other: Self) -> Self:
        """Data classification combines towards the most restrictive (highest rank)."""
        return self if self >= other else other


class TrustTag(StrEnum):
    """Trust tagging and inheritance (§19.1 & §19.2)."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"

    def combine_with(self, other: Self) -> Self:
        """Trust inheritance (§19.2): any untrusted input makes derived content untrusted."""
        if self == TrustTag.UNTRUSTED or other == TrustTag.UNTRUSTED:
            return TrustTag.UNTRUSTED
        return TrustTag.TRUSTED


class TaggedContent(BaseModel):
    """Wrapper for any payload carrying data governance and trust metadata."""

    model_config = ConfigDict(frozen=True)

    content: str
    classification: DataClassification = DataClassification.INTERNAL
    trust: TrustTag = TrustTag.UNTRUSTED
    source_identifier: str = Field(default="")
