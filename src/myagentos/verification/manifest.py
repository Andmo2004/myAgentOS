"""Test manifest integrity validation according to §13.5."""

from pydantic import BaseModel, ConfigDict, Field


class TestManifest(BaseModel):
    """Enforces test manifest integrity between baseline and candidate (§13.5)."""

    __test__ = False

    model_config = ConfigDict(frozen=True)

    baseline_test_ids: set[str] = Field(default_factory=set)
    expected_new_test_ids: set[str] = Field(default_factory=set)

    @property
    def all_expected_test_ids(self) -> set[str]:
        return self.baseline_test_ids | self.expected_new_test_ids

    def validate_candidate(
        self,
        executed_test_ids: set[str],
        failed_test_ids: set[str],
        skipped_test_ids: set[str],
    ) -> tuple[bool, str | None]:
        """Validates that no test was silently deleted, skipped, or failed (§13.5).

        Returns (True, None) or (False, reason).
        """
        # 1. Total tests must not drop
        missing = self.all_expected_test_ids - executed_test_ids
        if missing:
            return (
                False,
                f"Missing expected tests in candidate run ({len(missing)} missing): "
                f"{sorted(list(missing))[:5]}",
            )

        # 2. Baseline tests must not be turned into skipped
        newly_skipped = self.baseline_test_ids & skipped_test_ids
        if newly_skipped:
            return (
                False,
                f"Baseline tests cannot be turned into skipped ({len(newly_skipped)} skipped): "
                f"{sorted(list(newly_skipped))[:5]}",
            )

        # 3. No failures allowed in verification
        if failed_test_ids:
            return (
                False,
                f"Test execution failed ({len(failed_test_ids)} failed): "
                f"{sorted(list(failed_test_ids))[:5]}",
            )

        return True, None
