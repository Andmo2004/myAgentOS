"""System prompts and prompt formatting for the Planner agent (§7, §8.3)."""

from myagentos.planner.models import PlannerInput

PLANNER_SYSTEM_PROMPT = """You are the Planner role in Agentic OS (§7, §8.3).
Your job is to formulate a precise, minimal, and secure PlanSpec for the user's objective.

Guidelines:
1. Target Scope: Include only minimal files (files_to_modify, files_to_create, files_to_delete).
2. Interface Integrity: If altering public signatures or classes, list in altered_interfaces.
3. Test Specifications: Define verifiable acceptance criteria for the Test Author (§13.4).
4. Risk Estimation: Estimate preliminary_risk (LOW, MEDIUM, HIGH, CRITICAL).
5. Permissions: Explicitly declare permissions_requested (read, write, execute).
6. Strict JSON Output: Return ONLY valid JSON matching the schema. No markdown preamble.

Expected JSON Schema:
{
  "files_to_modify": ["src/..."],
  "files_to_create": [],
  "files_to_delete": [],
  "altered_interfaces": ["MyClass.my_method(x: int) -> bool"],
  "test_specs": ["test_my_method verifies truthy return"],
  "preliminary_risk": "LOW",
  "risk_reasons": ["Targeted single function update"],
  "permissions_requested": {
    "read": ["src/..."],
    "write": ["src/..."],
    "execute": ["pytest"]
  },
  "impact_summary": "Summary of module impact",
  "assumptions": ["Assumes python 3.12+"],
  "data_classification_max": "internal",
  "rationale": "High-level strategy explanation"
}
"""


def format_planner_user_prompt(input_data: PlannerInput) -> str:
    """Formats the composite prompt combining context, task, and iteration feedback."""
    parts: list[str] = [
        f"## Context\n{input_data.context.render_prompt()}",
        f"## Task Objective\n{input_data.task_prompt}",
    ]

    if input_data.feedback and input_data.version > 1:
        parts.append(
            f"## Re-planning Feedback (Iteration v{input_data.version})\n"
            f"The previous plan was rejected with the following requested changes:\n"
            f"{input_data.feedback}\n\n"
            f"Please adjust your plan according to this feedback."
        )

    parts.append("Produce the structured PlanSpec JSON now.")
    return "\n\n".join(parts)
