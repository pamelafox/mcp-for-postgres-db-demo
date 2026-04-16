# Instructions for coding agents

* Do not add comments indicating something you have removed, simply remove it and be done with it.
* Similarly, do not add comments indicating something you have changed; just make the change.
* If you are asked to copy a file, do a file copy and delete the old file.

## Python conventions

* All imports go at the TOP of the file, do NOT import inside functions or if statements.
* Do NOT use excessive try/catch statements, only use try/catch when explicitly requested. Most exceptions should propagate and become runtime errors.
* Use type annotations only for function definitions, do NOT use for variables or attributes.
* Do NOT add "pragma: no cover" or similar coverage-ignore comments, unless explicitly requested.

## Adding new dependencies

If the dependency is for the application (not for dev or testing):

* Add the new dependency to the `[project.dependencies]` list in `pyproject.toml`.
* Install the new dependencies:

    uv sync

If the dependency is for development or testing:

* Add the new dependency to the `[dependency-groups] dev` list in `pyproject.toml`.
* Install the new dependencies:
    uv sync --group dev

## Running tests

Install the dev requirements:

uv sync --group dev

Then run the tests with:

uv run python -m pytest