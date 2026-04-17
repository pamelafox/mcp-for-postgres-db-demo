"""Test dataset for evaluating MCP server variants.

Contains test cases with bee biodiversity queries categorized by type:
- species_search: Queries about species information
- observation_search: Queries about observations by location/date
- historical: Queries requiring historical data
- cross_table: Queries requiring both recent and historical data
- write: Queries that require adding/modifying data
"""

from dataclasses import dataclass


@dataclass
class BeeCase:
    """A single test case for bee biodiversity queries."""

    name: str
    prompt: str
    expected_tools: list[str]  # Tools that should be called (in any order)
    difficulty: str = "clear"  # clear, ambiguous, cross_table


# =============================================================================
# Test Cases
# =============================================================================

BEE_CASES: list[BeeCase] = [
    # --- Species search ---
    BeeCase(
        name="species_by_common_name",
        prompt="Find me information about leafcutter bees.",
        expected_tools=["search_species"],
        difficulty="clear",
    ),
    BeeCase(
        name="species_by_scientific_name",
        prompt="Look up Megachile rotundata.",
        expected_tools=["search_species"],
        difficulty="clear",
    ),
    # --- Recent observation search ---
    BeeCase(
        name="observations_near_location",
        prompt="Show me bee observations near San Francisco from March 2024.",
        expected_tools=["search_observations"],
        difficulty="clear",
    ),
    BeeCase(
        name="observations_specific_species",
        prompt="Have there been any Blue Orchard Bee sightings near Portland, Oregon in the last year?",
        expected_tools=["search_species", "search_observations"],
        difficulty="clear",
    ),
    BeeCase(
        name="observations_no_species_filter",
        prompt="What bees have been seen near Golden Gate Park in June 2024?",
        expected_tools=["search_observations"],
        difficulty="clear",
    ),
    # --- Historical observation search ---
    BeeCase(
        name="historical_specific_year",
        prompt="Were there any bumble bee observations near Seattle in 2015?",
        expected_tools=["search_species", "search_historical_observations"],
        difficulty="clear",
    ),
    BeeCase(
        name="historical_decade",
        prompt="Show me bee observations near Denver from 2005 to 2010.",
        expected_tools=["search_historical_observations"],
        difficulty="clear",
    ),
    # --- Cross-table queries (require both recent and historical) ---
    BeeCase(
        name="cross_table_any_time",
        prompt="Has anyone ever seen a sweat bee near Austin, Texas?",
        expected_tools=["search_species", "search_observations", "search_historical_observations"],
        difficulty="cross_table",
    ),
    BeeCase(
        name="cross_table_trend",
        prompt="How have bee observations changed near San Francisco between 2010 and 2024?",
        expected_tools=["search_observations", "search_historical_observations"],
        difficulty="cross_table",
    ),
    BeeCase(
        name="cross_table_comprehensive",
        prompt="Give me a complete history of leafcutter bee sightings near Los Angeles.",
        expected_tools=["search_species", "search_observations", "search_historical_observations"],
        difficulty="cross_table",
    ),
    # --- Ambiguous (which table?) ---
    BeeCase(
        name="ambiguous_no_date",
        prompt="Are there leafcutter bees in the Bay Area?",
        expected_tools=["search_species", "search_observations"],
        difficulty="ambiguous",
    ),
    BeeCase(
        name="ambiguous_old_date",
        prompt="What bees were observed near Chicago in 2019?",
        expected_tools=["search_historical_observations"],
        difficulty="ambiguous",
    ),
    # --- Write operations ---
    BeeCase(
        name="add_observation_with_name",
        prompt="I just saw a Western Honey Bee in my garden at 37.77, -122.42.",
        expected_tools=["search_species", "add_observation"],
        difficulty="clear",
    ),
]


def get_cases_by_difficulty(difficulty: str) -> list[BeeCase]:
    """Get test cases filtered by difficulty level."""
    return [c for c in BEE_CASES if c.difficulty == difficulty]
