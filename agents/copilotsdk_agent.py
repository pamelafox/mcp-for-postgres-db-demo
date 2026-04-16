"""GitHub Copilot SDK agent for testing MCP server variants.

Connects to a running MCP server over Streamable HTTP and runs queries.

Usage:
    # Start a server first:
    python servers/level4_typed.py

    # Run a query:
    python agents/copilotsdk_agent.py --query "What bees are active near SF in March?"
"""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from copilot import CopilotClient
from copilot.generated.session_events import SessionEvent, SessionEventType
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("bees_agent")
logger.setLevel(logging.INFO)

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

COPILOT_MODELS = [
    "gpt-5",
    "gpt-5.3-codex",
    "claude-sonnet-4",
    "claude-sonnet-4.5",
    "claude-haiku-4.5",
]
DEFAULT_COPILOT_MODEL = "gpt-5.4"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ToolCallInfo:
    """Information about a single tool call."""

    tool_name: str
    arguments: dict


@dataclass
class QueryResult:
    """Result of running a query against the agent."""

    output: str
    tool_calls: list[ToolCallInfo]
    reasoning: str | None = None
    error: str | None = None


# =============================================================================
# Query Runner
# =============================================================================


async def run_query(
    query: str,
    model: str | None = None,
) -> QueryResult:
    """Run a single query against the agent.

    Args:
        query: The user query to send
        model: Model name to use (default: gpt-5)

    Returns:
        QueryResult with output, tool calls, and optional reasoning
    """
    deployment = model or DEFAULT_COPILOT_MODEL

    tool_calls: list[ToolCallInfo] = []
    reasoning_parts: list[str] = []

    def handle_event(event: SessionEvent):
        if event.type == SessionEventType.TOOL_EXECUTION_START:
            if hasattr(event, "data") and event.data:
                data = event.data
                tool_name_val = getattr(data, "mcp_tool_name", None) or getattr(data, "tool_name", None)
                args = getattr(data, "arguments", None)
                if tool_name_val:
                    tool_calls.append(
                        ToolCallInfo(
                            tool_name=tool_name_val,
                            arguments=args if isinstance(args, dict) else {},
                        )
                    )
        elif event.type == SessionEventType.ASSISTANT_REASONING:
            if hasattr(event, "data") and event.data and hasattr(event.data, "content"):
                content = event.data.content
                if content:
                    reasoning_parts.append(str(content))

    try:
        async with CopilotClient() as client:
            session = await client.create_session(
                on_permission_request=lambda **kwargs: True,
                model=deployment,
                mcp_servers={
                    "bees": {"type": "http", "url": MCP_SERVER_URL},
                },
                system_message={
                    "mode": "append",
                    "content": (
                        "You help users explore bee biodiversity data. "
                        "The database contains observations of bee species from iNaturalist. "
                        "Always use the available MCP tools to query the database before answering. "
                        f"Today's date is {datetime.now().strftime('%B %-d, %Y')}."
                    ),
                },
            )
            session.on(handle_event)
            response = await session.send_and_wait(query, timeout=60.0)

        output = ""
        if response and hasattr(response, "data") and hasattr(response.data, "content"):
            output = response.data.content or ""
        reasoning = "\n\n".join(reasoning_parts) if reasoning_parts else None

        return QueryResult(
            output=output,
            tool_calls=tool_calls,
            reasoning=reasoning,
        )

    except Exception as e:
        logger.exception("Error running query")
        return QueryResult(output="", tool_calls=[], error=str(e))


# =============================================================================
# CLI
# =============================================================================

DEFAULT_QUERY = "What bees are active near San Francisco in March?"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run Copilot SDK agent against bees MCP server")
    parser.add_argument(
        "--query",
        type=str,
        default=DEFAULT_QUERY,
        help=f"Query to send to the agent (default: '{DEFAULT_QUERY}')",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        choices=COPILOT_MODELS,
        help=f"Model to use (default: {DEFAULT_COPILOT_MODEL})",
    )
    parser.add_argument(
        "--show-tool-calls",
        action="store_true",
        help="Print extracted tool calls after the run",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Print reasoning summary after the run",
    )
    return parser.parse_args()


async def main():
    """Run the agent with command line arguments."""
    args = parse_args()

    result = await run_query(
        query=args.query,
        model=args.model,
    )

    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"Result: {result.output}")

        if args.show_tool_calls:
            print("Tool calls:")
            for call in result.tool_calls:
                print(f"  {call.tool_name}: {json.dumps(call.arguments, default=str)}")

        if args.show_reasoning:
            print("Reasoning:")
            print(result.reasoning if result.reasoning else "(none)")


if __name__ == "__main__":
    asyncio.run(main())
