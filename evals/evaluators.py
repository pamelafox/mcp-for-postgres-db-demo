"""Evaluators for MCP server variant testing.

Evaluators check:
- Whether expected tools were called
- Whether tool arguments are reasonable
- Whether the right combination of tools was selected
"""

import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

from agents.pydanticai_agent import ToolCallInfo


@dataclass
class EvalResult:
    """Result of an evaluation."""

    passed: bool
    score: float  # 0.0 to 1.0
    message: str
    details: dict | None = None


def evaluate_tools_called(tool_calls: list[ToolCallInfo], expected_tools: list[str]) -> EvalResult:
    """Check if the expected tools were called (in any order).

    Scoring:
    - 1.0 if all expected tools were called (extras are OK)
    - Partial credit for subset matches
    - 0.0 if no expected tools were called
    """
    called_names = {tc.tool_name for tc in tool_calls}
    expected_set = set(expected_tools)

    matched = called_names & expected_set
    missing = expected_set - called_names
    extra = called_names - expected_set

    if not expected_set:
        return EvalResult(passed=True, score=1.0, message="No tools expected, none required")

    score = len(matched) / len(expected_set)

    if missing:
        return EvalResult(
            passed=False,
            score=score,
            message=f"Missing tools: {sorted(missing)}. Called: {sorted(called_names)}",
            details={"matched": sorted(matched), "missing": sorted(missing), "extra": sorted(extra)},
        )

    msg = f"All expected tools called: {sorted(expected_set)}"
    if extra:
        msg += f" (also called: {sorted(extra)})"
    details = {"matched": sorted(matched), "extra": sorted(extra)}
    return EvalResult(passed=True, score=score, message=msg, details=details)


def evaluate_no_mutation(tool_calls: list[ToolCallInfo]) -> EvalResult:
    """Check that no write/destructive tools were called (for read-only queries)."""
    destructive = {"add_observation", "delete_observation", "execute_sql"}
    called_destructive = {tc.tool_name for tc in tool_calls} & destructive
    if called_destructive:
        return EvalResult(
            passed=False,
            score=0.0,
            message=f"Destructive tools called: {sorted(called_destructive)}",
        )
    return EvalResult(passed=True, score=1.0, message="No destructive tools called")


def evaluate_has_spatial_params(tool_calls: list[ToolCallInfo]) -> EvalResult:
    """Check that observation search tools include lat/lon parameters."""
    spatial_tools = {"search_observations", "search_historical_observations"}
    for tc in tool_calls:
        if tc.tool_name in spatial_tools:
            if "lat" in tc.arguments and "lon" in tc.arguments:
                return EvalResult(passed=True, score=1.0, message=f"{tc.tool_name} has lat/lon params")
            return EvalResult(
                passed=False,
                score=0.5,
                message=f"{tc.tool_name} missing lat/lon params",
                details={"arguments": tc.arguments},
            )
    return EvalResult(passed=True, score=1.0, message="No spatial tools called (N/A)")


def evaluate_used_search_species_first(tool_calls: list[ToolCallInfo]) -> EvalResult:
    """Check that search_species was called before observation tools when species name is in the query.

    This validates the intended multi-step flow: resolve name → search by taxon_id.
    """
    obs_tools = {"search_observations", "search_historical_observations", "add_observation"}
    species_idx = None
    first_obs_idx = None

    for i, tc in enumerate(tool_calls):
        if tc.tool_name == "search_species" and species_idx is None:
            species_idx = i
        if tc.tool_name in obs_tools and first_obs_idx is None:
            first_obs_idx = i

    if first_obs_idx is None:
        return EvalResult(passed=True, score=1.0, message="No observation tools called (N/A)")

    if species_idx is not None and species_idx < first_obs_idx:
        return EvalResult(passed=True, score=1.0, message="search_species called before observation tools")

    if species_idx is None:
        return EvalResult(
            passed=False,
            score=0.0,
            message="Observation tools called without search_species first",
            details={"tool_order": [tc.tool_name for tc in tool_calls]},
        )

    return EvalResult(
        passed=False,
        score=0.5,
        message="search_species called after observation tools",
        details={"species_idx": species_idx, "first_obs_idx": first_obs_idx},
    )
