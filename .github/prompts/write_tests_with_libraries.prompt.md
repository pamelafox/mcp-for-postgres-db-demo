---
mode: agent
---

# Step 1: Write tests

Write tests for routes.py that test each API endpoint, using the fixtures in conftest.py.

The tests should test the local test database that is already seeded with data - so you shouldn't need any mocks.

Follow these guidelines:
- Use pytest.mark.parametrize to avoid repetitive code, like testing multiple input values for the same endpoint
- Use pytest.fixtures to set up any common test data or state
- Use pytest-snapshot to create snapshots for API responses, with assert_match to compare responses to snapshots
  https://pypi.org/project/pytest-snapshot/
- Use Faker to generate realistic fake data for names, dates, coordinates, etc.
  https://faker.readthedocs.io/
  Built-in Faker providers for common data types:
  https://faker.readthedocs.io/en/master/providers.html


# Step 2: Run tests

Once you've written all the tests, confirm that they pass:

pytest

# Step 3: Improve coverage

The goal is for the tests to cover all lines of code.

Generate a coverage report with:

pytest --cov --cov-report=annotate:cov_annotate

Open the cov_annotate directory to view the annotated source code.
There will be one file per source file. If a file has 100% source coverage, it means all lines are covered by tests, so you do not need to open the file.

For each file that has less than 100% test coverage, find the matching file in cov_annotate and review the file.

If a line starts with a ! (exclamation mark), it means that the line is not covered by tests.
Add tests to cover the missing lines.

Keep running the tests and improving coverage until all lines are covered.
DO NOT STOP until all lines are covered across all tested files -
the goal for TOTAL Cover is 100%.