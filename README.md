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

1. The studio opens with the full play visible. Choose a named play in the sidebar.
2. Select the **Key pass** milestone in the timeline to jump to the breakthrough and its on-screen facts.
3. Select **Start replay**, then select the timeline milestones to step through the sequence.
   **Full play** restores the overview; the slider allows manual seeking.
4. Read **Why this goal happened** for the explanation. Change the commentary
   style, language or focus player in the sidebar to personalize it.
5. Open **Recovery demo / advanced** only when demonstrating an intentional
   creative failure. Agent handoffs and earlier overlays are collapsed by default.

The selected moment names the player and action above the pitch. On-screen facts
show only active overlays; earlier ones remain available in their own expander.
Replay controls do not make new model calls. The native dark theme in
`.streamlit/config.toml` also styles widgets consistently; refresh the browser
or restart Streamlit if an already-open session retains its previous appearance.


### Compact studio layout

Quick guide opens the walkthrough on demand from the header. A small amber
pill identifies local failure simulation. Start replay, the event milestones
(including Key pass), and Full play share one wrapping control strip above the
compact clock. On narrow screens the controls wrap and the two main columns
stack. The header retains Show controls when the sidebar is collapsed.

Strict warning verification:

```sh
uv run python -W error -m unittest discover -s tests -v
```
