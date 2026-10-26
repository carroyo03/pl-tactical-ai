# PL Tactical AI

[![CI](https://github.com/carroyo03/pl-tactical-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/carroyo03/pl-tactical-ai/actions/workflows/ci.yml)

**[Open the Azure demo](https://pl-tactical-demo-studio.happyhill-6f6f935b.germanywestcentral.azurecontainerapps.io)**
— fictional goal sequences with offline narration. The app can scale to zero, so
the first visit may take longer to load.

PL Tactical AI is an explainable football analysis and commentary prototype for
analysts and broadcast teams. It turns structured goal-sequence events into an
interactive tactical replay and a personalized explanation of how the move unfolded.
It helps answer three questions: **Which pass stands out, who connects the attack,
and what evidence supports that interpretation?**

The Broadcast Studio lets you explore three fictional goal sequences, jump between
key events, inspect timed overlays and read commentary in English or Spanish.
Commentary can be tailored to a tactical analyst, a passionate fan or a casual
viewer, with an optional focus on a participating player.

## How it works

1. **Establish the facts.** The Tactical Analyst calculates pass metrics, identifies
   the highlighted pass and builds an inferred passing network from the events.
2. **Explain the play.** The Persona Narrator prepares commentary using those facts
   and the selected language, style and player focus.
3. **Check the explanation.** The Guardrail Critic validates supported claims and
   output requirements. A rejected draft can be retried once; if both attempts
   fail, a validated offline fallback is used. Tactical facts stay unchanged.

The interface exposes the evidence behind the analysis and includes selectable
local review scenarios. These deliberately introduce mistakes so the rejection,
correction and fallback paths can be inspected step by step.

## Current scope

- **Synthetic data only:** fictional players and authored football events, with no
  real Premier League match data or video event detection.
- **Episode-level analysis:** goal sequences and their explanations, rather than
  full-match recaps or a live match feed.
- **Explicit measurement limits:** packing compares a pass with a static defensive
  snapshot; passing connections are inferred; difficulty is a heuristic score,
  not a calibrated completion probability.
- **Works without cloud credentials:** the default narrator uses reviewed offline
  templates. Opt-in Groq narration is available locally and has undergone a small
  synthetic evaluation. The published Azure demo remains offline. An Azure OpenAI
  adapter is implemented, but a real Azure model deployment remains unvalidated.

The application combines **Python, FastAPI, Streamlit, DuckDB, NetworkX, Plotly
and Pydantic**, with a custom three-role orchestration workflow. The offline mode
supports reproducible development and demonstrations without model API calls.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from
the project root:

```sh
uv sync --locked
uv run streamlit run src/ui/app.py
```

Open the local URL printed by Streamlit and select a play. No Azure credentials
are needed for this mode. Backend setup and remote mode are described below.

## Development setup

### Local real-model preview

The Groq integration is opt-in and local only. Keep your Groq organization on the
Free plan with paid billing disabled. Put `GROQ_API_KEY` in the ignored root `.env`,
then run:

```sh
uv run python scripts/run_groq_studio.py
```

The launcher loads local settings without overriding existing environment values,
binds the studio to localhost and bypasses any remote API configuration. A deployed
studio can enable the same integration explicitly; see [Azure demo deployment](infra/README.md). Select
your options and press **Generate commentary**. Changing replay position or opening
an explanation does not call the model. Previous commentary remains labelled with
its original selections until a new request completes.

Only validated commentary is displayed. A shared, bounded in-memory cache reuses
identical accepted results. Model failures select a labelled offline explanation;
configuration errors are recorded without exposing upstream response bodies. The
generation and recovery window is 20 seconds with at most two provider calls.
These limits are per process and reset on restart; they are not account-wide
billing controls. The Azure budget does not cover Groq.

`GROQ_MODEL` selects an evaluation candidate. The local default is
`openai/gpt-oss-120b`, selected after a small three-candidate comparison and a
six-case check across the three plays and both languages. Five cases passed on
the first attempt and one required correction. That sample does not establish
general factual accuracy, availability or production performance. Manual review
also led to tighter checks and wording for language consistency. To
compare up to three candidates, first verify the Free plan in Groq Console:

```sh
uv run python scripts/evaluate_groq.py --confirm-free-plan
```

This separate evaluation makes at most six generation requests per model, each
with at most two provider calls. It is paced and can take several minutes. Results
and generated text stay in an ignored local report for quality review. It is never
run by CI. Network failures and quota limits count as evaluation outcomes, not as
evidence of model quality. No provider data-retention settings are changed by the
application. Ordinary offline startup remains credential-independent, and the
published Azure demo is not enabled for Groq by these local commands.

For the container build, local two-service setup and the proposed low-cost Azure
deployment, see [Azure demo deployment](infra/README.md). The deployment starts
with offline narration and does not require model quota.

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

## Continuous integration

The `CI` GitHub Actions workflow runs on pushes to `main`, pull requests and manual
dispatches. A single Ubuntu job installs the Python version in `.python-version`
and dependencies from `uv.lock`, runs the offline regression suite (including
Streamlit AppTest interactions), then verifies actual FastAPI and Streamlit server
startup with `scripts/check_startup.py`.

No repository secrets or Azure resources are required. Provider credentials are
not supplied, and the checks use the offline client. The startup check validates
HTTP readiness, not browser appearance. The workflow does not deploy the app.

Runs have read-only repository permissions and a ten-minute timeout. New runs
cancel older runs for the same branch or pull request; dependency caching avoids
unnecessary downloads. Actions are pinned to commit hashes, and Dependabot checks
for action updates weekly.

After pushing the workflow, open **Actions → CI** to inspect the first run. Once
it passes, `Offline tests and startup` can be selected as a required check in the
repository's branch rules; this workflow does not configure those rules itself.

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
Alternatively, set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` and
`AZURE_OPENAI_AUTH=entra` (no key) to sign in with Microsoft Entra ID through
`DefaultAzureCredential`: Azure CLI locally, or a managed identity in Azure. The
identity needs the **Cognitive Services OpenAI User** role on the resource.
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

Agent demo modes alter the active provider's draft locally after it is generated
(offline mock by default, or the local Groq model when enabled). The Guardrail Critic
is unchanged and checks the altered text against the original facts:

- Normal: regular offline generation, or the configured remote API.
- Simulate 1 Critic Retry: first draft fails, feedback repairs the second.
- Simulate Double Failure -> Fallback: two drafts fail, validated fallback wins.

Open **Test the safety checks** above the commentary and, under **How should the review behave?**, select **One correction** (the first draft is rejected and corrected) or
**Fallback** (both drafts are rejected and a fallback is used). A second selector,
**What should go wrong in the draft?**, offers six demonstrations: an invented
player, an incorrect receiver, a recovery assigned to the wrong player, an
incorrect duration, an incorrect pass accuracy, or missing scorer/connector names.
Only cases applicable to the selected episode are offered.

With Groq enabled, a scenario is started by an explicit **Run review scenario** button,
uses at most two model requests and is never served from the cache. The error is
introduced by the application, so a recovery shows the pipeline's resilience, not that
a model ignored an instruction. Each attempt records the provider draft, the alteration
(or why it could not be applied), and the critic's verdict. The scenario outcome
(completed, not detected, or not executed, for example after a provider failure) is
reported separately from the commentary outcome.

The review shows the actual rejected draft, an explanation of the recorded
validator feedback, and the episode facts that contradict the draft. A final
outcome explains whether the second attempt passed or a validated fallback was
used. The **Step-by-step explanation** expander is closed by default and explains fact preparation, draft checking and
final selection. Rejected drafts, plain-language reasons and supporting evidence
appear at the checking step. The accepted
text stays in the commentary above; validator messages, timing and handoffs are
grouped under **Technical details**.
All demonstration drafts are generated locally, including in remote API mode;
they are stored only in the UI session and never added to API responses.
Replay jumps reuse the result and review. Changing the mistake starts a new run;
returning to normal generation clears the demonstration review.

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
4. Use **Test the safety checks** to demonstrate success,
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

These checks validate supported English and Spanish claims within a defined
scope. They complement scenario-based quality evaluation; they do not establish
that every generated statement is correct.
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
controls. The public deployment keeps paid model selection disabled and adds
service authentication, bounded processing and operational monitoring. Runtime
settings and credentials are kept outside version control. Azure Container Apps
hosting has been verified as documented in
[the deployment guide](infra/README.md). Real model deployment and provider
quality/latency evaluation remain pending.
