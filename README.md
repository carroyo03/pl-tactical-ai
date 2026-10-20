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

## API backend

Start from the project root:

```sh
uv run uvicorn src.api.app:app --reload
```

The application loads `data/raw/sample_goal_episode.json` into in-memory DuckDB
at startup. Generate it first if missing:

```sh
uv run python -m src.ingest.mock_generator
```

- `GET /goals`: sorted JSON array of available goal IDs.
- `GET /goals/{goal_id}/intelligence?persona=TACTICAL_ANALYST&language=en`:
  JSON containing `episode`, `analysis`, and `narrative`.
- `/docs`: interactive API documentation.

Unknown goals return 404; unsupported persona/language values return 422.
The default narrator is offline. Setting all three of `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_DEPLOYMENT` selects Azure instead.
`AZURE_OPENAI_API_VERSION` defaults to `2024-10-21`; the deployment must support
Structured Outputs. Export variables in the process environment; `.env` files
are not loaded automatically. Partial Azure configuration uses the Mock.

Each app process owns one in-memory repository. Lifespan startup loads the
sample; shutdown closes DuckDB and any app-created Azure client. Tests can use
`create_app(client=MockLLMClient(), sample_path=...)` to stay offline regardless
of environment variables. Injected clients remain caller-owned.

## Broadcast demo workflow

Default API startup now seeds three reproducible fictional scenarios directly
from `generate_mock_episodes()`; it does not depend on a possibly stale local
sample. Custom `sample_path` fixtures remain isolated. Running the generator
also writes all three JSON files for inspection.

Discover the scenarios with `GET /goals`, then request, for example:

```text
GET /goals/SYNTH_GOAL_01/broadcast?persona=PASSIONATE_FAN&language=en&focus_player_id=P_04
```

The enriched response includes normalized-pitch metrics, timed overlay data,
explicit focus participation and orchestration telemetry. The original
`/intelligence` response still has exactly three keys. Broadcast generation uses
three specialized roles with one feedback-driven retry and a validated degraded
fallback. No meters or ball speeds are inferred. See spec.md for formulas, units,
classification thresholds and limitations. Overlay rendering belongs to the
upcoming UI; currently these are machine-readable replay markers.
