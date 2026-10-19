# PL Tactical AI

Install dependencies and the project as an editable package:

```sh
uv sync
```

`uv run` automatically synchronizes the project environment. Imports such as
`from src.analytics.schemas import GoalEpisode` work from any project directory
because the project is installed, rather than relying on the working directory.

Run all tests from the project root:

```sh
uv run python -m unittest discover -s tests -v
```

Or run the test file directly from the tests directory:

```sh
cd tests
uv run test_tactical_engine.py
```

When running Python directly, use the project's synchronized virtual environment.
