"""Evaluation runner for MCP server variant testing.

Runs test cases across different server levels and tool configurations,
collecting metrics on tool-calling accuracy and tool selection.

Usage:
    # Start a server first:
    python servers/level4_typed.py

    # Run evaluation:
    python evals/runner.py

    # Run with specific cases:
    python evals/runner.py --cases species_by_common_name,observations_near_location
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.copilotsdk_agent import ToolCallInfo, run_query
from evals.dataset import BEE_CASES, BeeCase
from evals.evaluators import EvalResult, evaluate_tools_called

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("eval_runner")
logger.setLevel(logging.INFO)


def get_model_name() -> str:
    """Get the model name."""
    return os.environ.get("COPILOT_MODEL", "gpt-5")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RunResult:
    """Result of a single test case run."""

    case_name: str
    user_query: str
    tool_calls: list[ToolCallInfo]
    eval_results: dict[str, EvalResult]
    overall_score: float
    agent_output: str
    reasoning: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


@dataclass
class Summary:
    """Summary metrics for a run."""

    total_cases: int = 0
    passed_cases: int = 0
    total_score: float = 0.0
    total_latency_ms: float = 0.0
    eval_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def avg_score(self) -> float:
        return self.total_score / self.total_cases if self.total_cases > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_cases if self.total_cases > 0 else 0.0


# =============================================================================
# Runner
# =============================================================================


async def run_single_case(
    case: BeeCase,
    tool_names: list[str] | None = None,
    model: str | None = None,
) -> RunResult:
    """Run a single test case."""
    t0 = time.perf_counter()
    query_result = await run_query(
        tool_names=tool_names or [],
        query=case.prompt,
        model=model,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    tool_calls = [
        ToolCallInfo(tool_name=tc.tool_name, arguments=tc.arguments)
        for tc in query_result.tool_calls
    ]

    if query_result.error:
        logger.error(f"Error running case {case.name}: {query_result.error}")
        return RunResult(
            case_name=case.name,
            user_query=case.prompt,
            tool_calls=[],
            eval_results={},
            overall_score=0.0,
            agent_output="",
            latency_ms=latency_ms,
            error=query_result.error,
        )

    eval_results = {"tools_called": evaluate_tools_called(tool_calls, case.expected_tools)}
    scores = [er.score for er in eval_results.values()]
    overall_score = sum(scores) / len(scores) if scores else 0.0

    return RunResult(
        case_name=case.name,
        user_query=case.prompt,
        tool_calls=tool_calls,
        eval_results=eval_results,
        overall_score=overall_score,
        agent_output=query_result.output,
        reasoning=query_result.reasoning,
        latency_ms=latency_ms,
    )


async def run_evaluation(
    cases: list[BeeCase],
    tool_names: list[str] | None = None,
    model: str | None = None,
) -> tuple[list[RunResult], Summary]:
    """Run evaluation across all cases."""
    results: list[RunResult] = []
    summary = Summary()

    for case in cases:
        logger.info(f"Running: {case.name}")
        result = await run_single_case(
            case=case,
            tool_names=tool_names,
            model=model,
        )
        results.append(result)

        summary.total_cases += 1
        summary.total_score += result.overall_score
        if result.overall_score >= 1.0:
            summary.passed_cases += 1
        if result.latency_ms:
            summary.total_latency_ms += result.latency_ms

        status = "PASS" if result.overall_score >= 1.0 else "FAIL"
        logger.info(f"  {status} (score={result.overall_score:.2f}, {result.latency_ms:.0f}ms)")
        for name, er in result.eval_results.items():
            symbol = "✓" if er.passed else "✗"
            logger.info(f"    {symbol} {name}: {er.message}")

    return results, summary


def print_summary(summary: Summary, model_name: str):
    """Print evaluation summary."""
    print("\n" + "=" * 60)
    print(f"Model: {model_name}")
    print(f"Cases: {summary.total_cases}")
    print(f"Passed: {summary.passed_cases}/{summary.total_cases}")
    print(f"Avg Score: {summary.avg_score:.2f}")
    print(f"Avg Latency: {summary.avg_latency_ms:.0f}ms")
    print("=" * 60)


def save_results(results: list[RunResult], summary: Summary, output_dir: str, model_name: str):
    """Save results to JSON."""
    os.makedirs(output_dir, exist_ok=True)

    data = {
        "model": model_name,
        "summary": {
            "total_cases": summary.total_cases,
            "passed_cases": summary.passed_cases,
            "avg_score": summary.avg_score,
            "avg_latency_ms": summary.avg_latency_ms,
        },
        "results": [
            {
                "case_name": r.case_name,
                "user_query": r.user_query,
                "overall_score": r.overall_score,
                "tool_calls": [{"tool_name": tc.tool_name, "arguments": tc.arguments} for tc in r.tool_calls],
                "eval_results": {
                    name: {"passed": er.passed, "score": er.score, "message": er.message}
                    for name, er in r.eval_results.items()
                },
                "agent_output": r.agent_output,
                "reasoning": r.reasoning,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in results
        ],
    }

    path = os.path.join(output_dir, "results.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved results to {path}")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run MCP server evaluation")
    parser.add_argument(
        "--cases",
        type=str,
        default="",
        help="Comma-separated list of case names (default: all cases)",
    )
    parser.add_argument(
        "--tools",
        type=str,
        default="",
        help="Comma-separated list of tool names to filter to (default: all tools)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="evals/runs",
        help="Output directory for results",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use (default: gpt-5)",
    )
    return parser.parse_args()


async def main():
    """Run the evaluation."""
    args = parse_args()
    load_dotenv(override=True)

    model_name = args.model or get_model_name()
    tool_names = [t.strip() for t in args.tools.split(",") if t.strip()] if args.tools else None

    if args.cases:
        case_names = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in BEE_CASES if c.name in case_names]
    else:
        cases = BEE_CASES

    logger.info(f"Running {len(cases)} cases with model {model_name}")
    if tool_names:
        logger.info(f"Filtering to tools: {tool_names}")

    results, summary = await run_evaluation(
        cases=cases,
        tool_names=tool_names,
        model=args.model,
    )

    print_summary(summary, model_name)
    save_results(results, summary, args.output, model_name)


if __name__ == "__main__":
    asyncio.run(main())
