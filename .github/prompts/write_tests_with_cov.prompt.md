---
mode: agent
---

# Step 1: Write tests

Write tests for routes.py that test each API endpoint, using the fixtures in conftest.py.

The tests should test the local test database that is already seeded with data - so you shouldn't need any mocks.

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