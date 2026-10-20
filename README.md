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

The default application seeds three canonical synthetic episodes in in-memory DuckDB.
To export reproducible JSON fixtures locally:

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
canonical episodes; shutdown closes DuckDB and any app-created Azure client. Tests can use
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

## Broadcast Studio UI

Launch the self-contained studio from the project root:

```sh
uv sync
uv run streamlit run src/ui/app.py
```

Open `http://localhost:8501`. Local mode seeds the three fictional episodes and
runs DuckDB, the tactical engine and the orchestrator in process, using the
Mock client. No API server, credentials or generated JSON files are required.
The UI has been verified with the locked Streamlit/Plotly versions.

Select an episode, persona, narrative language and optional focus player. The
external-player option demonstrates absence without attributing involvement.
Move the replay clock to reveal events and overlays at their relative times.
The top metrics and commentary describe the full episode; the pitch and overlay
cards follow the clock. History cards remain visible and are muted. A zero-time
focused recovery may already have an overlay at the start of replay.

Agent demo modes intentionally inject invalid creative drafts locally:

- Normal: regular offline generation, or the configured remote API.
- Simulate 1 Critic Retry: first draft fails, feedback repairs the second.
- Simulate Double Failure -> Fallback: two drafts fail, validated fallback wins.

Simulations are explicitly labelled and never send failure-injection requests
to a remote service. Clock changes reuse the stored result and do not generate
narratives. Changing controls or pressing Regenerate narrative starts a new run.

To consume the FastAPI backend instead:

```sh
uv run uvicorn src.api.app:app --port 8000
```

In a second terminal:

```sh
API_BASE_URL=http://127.0.0.1:8000 uv run streamlit run src/ui/app.py
```

Remote mode discovers IDs through `/goals`, fetches episode data through
`/intelligence` once per selected episode, and requests `/broadcast` when
narrative controls change. With Azure enabled on that backend, both the initial
intelligence request and broadcast generation may incur model calls. Use local
mode for a token-free demo. Set API_BASE_URL in the process environment; `.env`
is not loaded automatically. Unset it to return to local mode.

Run UI tests or the complete offline suite:

```sh
uv run python -m unittest discover -s tests -p 'test_ui.py' -v
uv run python -m unittest discover -s tests -v
```

UI tests include Streamlit AppTest interactions and may take longer than the
core analytics-only tests. They never require a browser or external network.

### First visit: a guided walkthrough

1. Choose an episode under **Choose a play**. The six metrics describe the full episode.
2. Use **Key Events** on the left to inspect a moment, the pitch and synchronized overlays.
3. Read **Why this goal happened** on the right. Change style, language or focus there.
   Personalization preserves the replay position; changing episodes resets it.
4. Use **Agent behavior** above the telemetry diagram to demonstrate success,
   one critic repair, or a validated safe fallback. Help is available in the header.
5. Earlier overlays and agent handoffs are available in their expanders.

Local canonical scenarios include an optional event-time synthetic reconstruction:
eleven opponents including a goalkeeper, plus the participating attackers. The
pitch advances these positions only when the corresponding event is reached.
This is an authored illustration, labelled **Synthetic reconstruction · Offside
not assessed**, with no claim of tracking, ball-flight timing or refereeing.
Crosses at the key pass show the separate, immutable five-defender packing
reference. Reconstruction positions never change packing or broadcast metrics.

The legacy episode/intelligence JSON is unchanged. Only `/broadcast` adds the
optional `reconstruction` field (`synthetic-reconstruction-v1`). External or
modified episodes without authored frames use the existing static-snapshot view.
The generator exports three additional `*_reconstruction.json` files alongside
the three original episode files. Replay frames are not interpolated.

At tablet widths up to 1180px, the tactical and narrative domains stack; desktop
uses two columns. Phone layouts use two-column milestones and reflowing legends.
Narrative/source changes invalidate cached local results. Restart the Streamlit
process if an already-running session retains imported code from a prior version.

Strict warning verification:

```sh
uv run python -W error -m unittest discover -s tests -v
```
