"""Microsoft Agent Framework agent for testing MCP server variants.

Connects to a running MCP server over Streamable HTTP and runs queries
using the Microsoft Agent Framework with Azure OpenAI.

Usage:
    # Start a server first:
    uv run servers/level4_typed.py

    # Run a query:
    uv run agents/agentframework_agent.py --query "What bees are active near SF in March?"
"""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import AzureDeveloperCliCredential, get_bearer_token_provider
from dotenv import load_dotenv
from rich.logging import RichHandler

load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(message)s", datefmt="[%X]", handlers=[RichHandler()])
logger = logging.getLogger("agentframework")
logger.setLevel(logging.INFO)

# =============================================================================
# Configuration
# =============================================================================

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp/")


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
# Model Configuration
# =============================================================================


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")


def get_client(deployment: str | None = None):
    """Configure the chat client. Uses Ollama if --ollama flag is set, otherwise Azure OpenAI."""
    ollama_url = os.getenv("USE_OLLAMA")
    if ollama_url:
        return OpenAIChatClient(
            base_url=OLLAMA_BASE_URL,
            api_key="ollama",
            model=deployment or OLLAMA_MODEL,
        )

    credential = AzureDeveloperCliCredential(tenant_id=os.environ["AZURE_TENANT_ID"])
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

    return OpenAIChatClient(
        base_url=f"{os.environ['AZURE_OPENAI_ENDPOINT']}/openai/v1/",
        api_key=token_provider,
        model=deployment or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"),
    )


def build_chat_options(
    seed: int | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    """Build chat options dict for ChatAgent.

    Args:
        seed: Optional seed for determinism/reproducibility
        temperature: Optional sampling temperature
        reasoning_effort: Optional reasoning effort level (low, medium, high)

    Returns:
        Dict of chat options to pass to ChatAgent's default_options.
    """
    options: dict = {}
    if seed is not None:
        options["seed"] = seed
    if temperature is not None:
        options["temperature"] = temperature
    if reasoning_effort is not None:
        # Request both reasoning effort and summary (to get text_reasoning content back)
        options["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
    return options


# =============================================================================
# Tool Call Extraction
# =============================================================================


def extract_tool_calls(result) -> list[ToolCallInfo]:
    """Extract tool call information from agent result.

    Agent Framework stores tool calls as Content objects in message.contents
    with type='function_call' or 'mcp_server_tool_call'.
    """
    tool_calls = []

    if hasattr(result, "messages"):
        for message in result.messages:
            if hasattr(message, "contents"):
                for content in message.contents:
                    content_type = getattr(content, "type", None)

                    if content_type == "function_call":
                        # Standard function calls
                        name = getattr(content, "name", None)
                        args = getattr(content, "arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        if name:
                            tool_calls.append(ToolCallInfo(tool_name=name, arguments=args or {}))

                    elif content_type == "mcp_server_tool_call":
                        # MCP tool calls
                        name = getattr(content, "tool_name", None)
                        args = getattr(content, "arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        if name:
                            tool_calls.append(ToolCallInfo(tool_name=name, arguments=args or {}))

    return tool_calls


def extract_reasoning(result) -> str | None:
    """Extract model-provided reasoning summary text from agent result.

    Agent Framework stores reasoning as Content objects in message.contents
    with type='text_reasoning'. The reasoning text is in the 'text' attribute.
    """
    reasoning_parts = []

    if hasattr(result, "messages"):
        for message in result.messages:
            if hasattr(message, "contents"):
                for content in message.contents:
                    content_type = getattr(content, "type", None)
                    if content_type == "text_reasoning":
                        text = getattr(content, "text", None)
                        if text:
                            reasoning_parts.append(text)

    return "\n\n".join(reasoning_parts) if reasoning_parts else None


# =============================================================================
# Query Runner
# =============================================================================


async def run_query(
    query: str,
    model: str | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> QueryResult:
    """Run a single query against the agent.

    Args:
        query: The user query to send
        model: Optional deployment name (defaults to AZURE_OPENAI_CHAT_DEPLOYMENT env var)
        seed: Optional seed for determinism/reproducibility
        temperature: Optional sampling temperature
        reasoning_effort: Optional reasoning effort level (low, medium, high)

    Returns:
        QueryResult with output, tool calls, and optional error.
    """
    client = get_client(model)
    chat_options = build_chat_options(seed=seed, temperature=temperature, reasoning_effort=reasoning_effort)

    try:
        async with (
            MCPStreamableHTTPTool(
                name="Bees MCP Server",
                url=MCP_SERVER_URL,
            ) as mcp_server,
            Agent(
                client=client,
                name="Bees Agent",
                instructions=(
                    "You help users explore bee biodiversity data. "
                    "The database contains observations of bee species from iNaturalist. "
                    "Always use the available MCP tools to query the database before answering. "
                    f"Today's date is {datetime.now().strftime('%B %-d, %Y')}."
                ),
                default_options=chat_options if chat_options else None,
            ) as agent,
        ):
            result = await agent.run(query, tools=mcp_server)

            tool_calls = extract_tool_calls(result)
            reasoning = extract_reasoning(result)

            return QueryResult(
                output=result.text,
                tool_calls=tool_calls,
                reasoning=reasoning,
            )

    except Exception as e:
        logger.exception("Error running query")
        return QueryResult(
            output="",
            tool_calls=[],
            error=str(e),
        )


# =============================================================================
# Main (CLI)
# =============================================================================

DEFAULT_QUERY = "What bees are active near San Francisco in March?"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run Agent Framework agent against bees MCP server")
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
        help="Model deployment name (defaults to AZURE_OPENAI_CHAT_DEPLOYMENT env var)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature (e.g., 0-2). If omitted, provider default is used.",
    )
    parser.add_argument(
        "--reasoning",
        type=str,
        default=None,
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort level (none, minimal, low, medium, high, xhigh). If omitted, provider default is used.",
    )
    parser.add_argument(
        "--show-tool-calls",
        action="store_true",
        help="Print extracted tool calls after the run (default: off)",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Print extracted reasoning summary text after the run (default: off)",
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use local Ollama instead of Azure OpenAI",
    )
    return parser.parse_args()


async def main():
    """Run the agent with command line arguments."""
    args = parse_args()
    if args.ollama:
        os.environ["USE_OLLAMA"] = "1"

    result = await run_query(
        query=args.query,
        model=args.model,
        seed=args.seed,
        temperature=args.temperature,
        reasoning_effort=args.reasoning,
    )

    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"Result: {result.output}")

        if args.show_tool_calls:
            print("Tool calls:")
            if result.tool_calls:
                for call in result.tool_calls:
                    print(f"- {call.tool_name}: {call.arguments}")
            else:
                print("- (none)")

        if args.show_reasoning:
            print("Reasoning summary:")
            print(result.reasoning if result.reasoning else "(none returned)")


if __name__ == "__main__":
    asyncio.run(main())
