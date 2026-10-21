# PL Tactical AI

Install dependencies and the project as an editable package:

```sh
uv sync --locked
```

`uv run` automatically synchronizes the project environment. Imports such as
`from src.analytics.schemas import GoalEpisode` work from any project directory
because the project is installed, rather than relying on the working directory.

The checked-in `.python-version` selects Python 3.14.2; the supported minor is
3.14. The lockfile pins the tested dependencies. Install `uv`, then run commands
from the project root. No generated data files or Azure credentials are required.

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
classification thresholds and limitations. The studio renders these markers
against the selected synthetic replay event.

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
Select a Key Events milestone to reveal events and overlays at their relative times.
The top metrics and commentary describe the full episode; the pitch and overlay
cards follow the clock. History cards remain visible and are muted. A zero-time
focused recovery may already have an overlay at the start of replay.

Agent demo modes intentionally inject invalid creative drafts locally:

- Normal: regular offline generation, or the configured remote API.
- Simulate 1 Critic Retry: first draft fails, feedback repairs the second.
- Simulate Double Failure -> Fallback: two drafts fail, validated fallback wins.

Simulations are explicitly labelled and never send failure-injection requests
to a remote service. Clock changes reuse the stored result and do not generate
narratives. Changing narrative controls starts a new run.

### Explain a tactical result

Open **Why these results?** below the narrative for full-episode evidence:
the selected pass, its strict X interval and counted defender references;
the inferred passing connections and pivot centrality scores; chronological
tie-breaks; and the ordered classification rule. Pass accuracy displays its
denominator, for example `100% (2/2)`. Difficulty remains a documented heuristic.

Packing, key-pass selection and the pass graph now consistently consider only
completed scoring-team passes. Rival events remain on the replay clock and can
interrupt recipient inference. A quick-transition label requires the first
chronological event to be a successful scoring-team recovery within ten seconds
of the goal. These corrections affect mixed-team or failed-recovery inputs;
the three canonical scenarios retain their existing analysis values.

The existing episode and analysis contracts are unchanged. `/broadcast` adds
optional `tactical_evidence` with version `tactical-evidence-v1`; older responses
without it still parse, and the studio reports missing evidence instead of
calculating substitute facts. Evidence is computed by the analyst before creative
generation and does not change on retry or fallback.

The legacy central-breakthrough label is retained for compatibility; it means
packing is at least three after the recovery rule fails, not an observed central
channel. The zero-centrality pivot tie is reported explicitly. Neither these
labels nor the authored reconstruction establish causality, continuous possession,
ball speed, or time-aligned defensive movement.

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

## Reliability and provider transparency

The editorial card reports the actual final narrative source: **Offline mock**,
**Azure OpenAI**, or **Offline fallback**. Telemetry separately reports the generator
that attempted the drafts. Older remote APIs without this metadata display
**Provider not reported**. Local studio mode always uses the Mock; Azure environment
variables apply to the API process. To use it, start the API with exported Azure
variables and set `API_BASE_URL=http://127.0.0.1:8000` for Streamlit. `.env.example`
is a reference template, not an automatically loaded configuration file.

The critic audits recognized English/Spanish packing and defender counts (digits
and number words), labelled accuracy/difficulty/distance, numeric values, explicit
zones and known-player pivot/scorer/key-pass claims. It rejects unsupported physical
units. Headline and commentary are audited separately. Recognized actor/action
patterns are also checked against the recorded events: capitalized multiword
names in actor/recipient positions must be known; carries, shots, successful
recoveries and completed passes require corresponding player events; explicit
pass recipients must follow the pass immediately on the full event clock.
Common passive scorer/role claims, labelled episode duration and completion
counts are checked too. Player-level counts use that player's attempts, while
team counts use scoring-team attempts. Percentages are reserved for episode
pass accuracy. The original invented-player example now triggers repair, or
validated fallback if the second attempt also fails.

These checks recognize specific English/Spanish constructions; they are not a
general named-entity recognizer or proof that every paraphrase or nonnumeric
sentence is true. Single-word or lowercase invented names, indirect/passive
action paraphrases and broader semantic contradictions can escape the audit.
Reviewed bilingual Mock templates
remain the token-free default; there is no automatic translation dependency.

Production SDK requests have a 10-second timeout, zero SDK retries and a
600-completion-token cap. The broadcast orchestrator makes at most two attempts.
Timeouts, connection failures, 429, transient 408/409/5xx responses, explicit refusals
and invalid drafts enter the existing bounded recovery/fallback path. Feedback
contains sanitized failure categories, not raw upstream response bodies. Local
fallback latency is not Azure latency; two failed requests can take roughly
20 seconds plus processing. Authentication/configuration errors and programming
bugs propagate for correction. The legacy intelligence route returns 503 for
recoverable provider unavailability; its success JSON keeps the original three keys.

Check the complete suite and actual local server startup:

```sh
uv run --locked python -W error -m unittest discover -s tests -v
uv run --locked python scripts/check_startup.py
```

The startup check launches FastAPI and Streamlit on ephemeral **127.0.0.1** ports,
checks real HTTP readiness, verifies offline broadcast and the legacy contract,
and closes both processes. It deliberately removes Azure variables from its child
processes so it cannot spend model tokens. Streamlit rendering and interaction are
covered separately by AppTest; the health check is not a browser visual test.

Do not expose the paid API publicly before adding authentication and request/cost
controls. This repository has not yet demonstrated a real Azure deployment or
provider quality/latency evaluation.
