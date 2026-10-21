# Tactical AI Engine — Technical Specification

## Architecture

- `src/analytics/schemas.py`: strict Pydantic contracts.
- `src/ingest/repository.py`: `DuckDBRepository` owns a private in-memory
  connection. `load_json(path)` validates and stores one episode; `save(episode)`
  upserts by goal ID; `get(goal_id)` returns a validated model or raises
  `KeyError`. Context manager support closes the connection. Nested payloads
  are stored as JSON. A future Fabric/Parquet adapter can return the same model.
- `src/analytics/tactical_engine.py`: `TacticalEngine.analyze(episode)` takes
  `GoalEpisode` and returns `TacticalAnalysisResponse`. No I/O or source-specific
  dependencies; only NetworkX and mathematics.

## Canonical JSON contracts

Generator field names are authoritative; no legacy aliases.
All models use strict validation, forbid extra fields, reject NaN/infinity,
reject numeric strings and string booleans. Coordinates are in [0, 100].
Identifiers are nonempty strings, not necessarily UUIDs.

### GoalEpisode

- `goal_id`, `match_id`: identifiers.
- `timestamp_goal`: finite nonnegative seconds.
- `scoring_team`, `conceding_team`: HOME or AWAY, distinct.
- `events`: nonempty list of MatchEvent; unique event IDs, matching match ID,
  timestamps no later than goal. The engine stably sorts by timestamp;
  equal timestamps preserve input order.
- `defenders_snapshot`: list of DefenderPosition, unique by player ID.

### MatchEvent

- `event_id`, `match_id`, `player_id`, `player_name`: nonempty strings.
- `timestamp_sec`: finite nonnegative seconds on the same clock as the goal.
- `period`: 1 or 2; `team`: HOME or AWAY.
- `event_type`: PASS, CARRY, RECOVERY, SHOT, DEFENSIVE_DUEL.
- `start_x`, `start_y`: coordinates.
- `end_x`, `end_y`: optional nullable coordinates; PASS requires non-null end_x.
- `is_successful`: boolean.

### DefenderPosition

- `player_id`: identifier; `x`, `y`: coordinates.

## Deterministic business rules

Attack is normalized towards increasing X.

### Packing

For each successful scoring-team PASS, count defenders with
`start_x < defender.x < end_x`. Exclude endpoints; lateral/backward passes
score zero. `sequence_packing_score` is MAX of per-pass scores (default zero),
never their sum. Equal positive scores choose the earliest chronological pass.
With no positive score, breakdown_zone is null.

The same static snapshot is used for each pass. MAX avoids accumulating
repeated counts, but is still a static approximation, not time-aligned tracking.
The input snapshot has no timestamp; no timing is inferred from mock comments.

### Pass graph

NetworkX DiGraph: for each successful scoring-team PASS, connect its author to the player of
its immediately following event in the full sorted sequence, including SHOT.
This infers the recipient because the input has no explicit recipient field.
Only connect different players of the scoring team. A rival next event interrupts
inference; do not remove it and skip ahead to a later scoring-team event.
A terminal pass has no edge.
No recovery edges, self-loops or weights. Repeated edges collapse.
Use unweighted normalized betweenness centrality. Return player ID; ties select
the player first seen chronologically, then lexicographic ID as final fallback.
Empty graph returns null.

### Breakdown zone

Use start_x of the earliest maximum-packing pass with positive score:

- [0, 33.3): Defensive Third.
- [33.3, 66.6): Middle Third.
- [66.6, 100]: Attacking Third.

These are the requested decimal cutoffs, not mathematical thirds at 100/3.

### Tactical cause (ordered precedence)

1. First chronological event is a successful scoring-team RECOVERY and
   `timestamp_goal - first.timestamp_sec <= 10`:
   `Quick transition after recovery`.
2. Otherwise, sequence_packing_score >= 3:
   `Central breakthrough through a vertical pass`.
3. Otherwise: `Positional attack`.

The label strings and precedence are preserved for compatibility. These are
ordered heuristics, not causal inference. In particular, the central-breakthrough
rule does not inspect Y or prove a central channel; positional attack is a default
classification, not a measured possession-control state. A failed or rival
recovery cannot trigger the quick-transition rule. All timestamps remain on the
episode clock; scoring-team eligibility does not establish continuous possession.

## TacticalAnalysisResponse

- `sequence_packing_score`: nonnegative strict integer.
- `tactical_pivot`: nonempty player ID or null.
- `breakdown_zone`: one of the three exact zone labels above or null.
- `tactical_cause`: one of the three exact English labels above.

Sample expectation: score 3, pivot P_10, Middle Third,
Quick transition after recovery (8.2 seconds).

## Local usage

Run from the project root:

```python
from src.ingest.repository import DuckDBRepository
from src.analytics.tactical_engine import TacticalEngine

with DuckDBRepository() as repository:
    episode = repository.load_json('data/raw/sample_goal_episode.json')
    result = TacticalEngine().analyze(repository.get(episode.goal_id))
    print(result.model_dump_json(indent=2))
```

Verification: `.venv/bin/python -m unittest discover -s tests -v`.

## Hybrid persona narrator

`src/agents/narrator.py` exposes `PersonaNarrator.narrate(episode, analysis,
persona=..., language=...) -> NarrativeOutput`.

- Supported personas: TACTICAL_ANALYST, PASSIONATE_FAN, CASUAL_VIEWER.
- Supported languages: en, es. Unsupported values fail before client calls.
- `tactical_breakdown` is assembled exclusively by code from the supplied engine
  output, using localized zone/cause labels and the real pivot name. Missing
  pivot/zone values have explicit localized descriptions.
- The LLM receives the unchanged engine output, ID/name associations and full
  chronologically ordered events. Equal timestamps preserve input order.
- The scorer is inferred only from a successful scoring-team SHOT at exactly
  timestamp_goal. Multiple candidates fail; without a known scorer, a known
  pivot is required. Conflicting player names or an unknown pivot ID fail.
- Only `CreativeOutput` (headline, commentary) is requested through Structured
  Outputs. NarrativeOutput adds the deterministic tactical_breakdown.
- Headlines contain 1–12 whitespace-separated words. Commentary must mention
  the scorer or pivot by full name (case-insensitive, word boundaries).
  Headline and commentary reject known internal identifiers and P_/DEF_/ev_
  patterns. Failures raise Pydantic ValidationError, without silent retries.
- These checks do not prove semantic truth of free-form text or verify language
  or tone. The deterministic breakdown preserves supplied metrics; the prompt
  forbids invented events and recalculation in creative fields.
- `LLMClient` is injectable. Default `MockLLMClient` never imports the Azure SDK,
  reads credentials or makes network calls. Production uses an explicitly
  injected `AzureOpenAIClient` with an Azure SDK client and deployment name.
- Azure refusals, missing parsed responses and incomplete completions fail
  explicitly. Network/API errors propagate; no silent Mock fallback.

### Narrator usage

```python
from src.agents.narrator import PersonaNarrator

narrative = PersonaNarrator().narrate(
    episode, result, persona='PASSIONATE_FAN', language='es',
)
print(narrative.model_dump_json(indent=2))
```

Production initialization (no secrets hardcoded):

```python
import os
from openai import AzureOpenAI
from src.agents.narrator import AzureOpenAIClient, PersonaNarrator

sdk = AzureOpenAI(
    azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
    api_key=os.environ['AZURE_OPENAI_API_KEY'],
    api_version=os.environ['AZURE_OPENAI_API_VERSION'],
    timeout=10.0,
    max_retries=0,
)
narrator = PersonaNarrator(AzureOpenAIClient(
    sdk, deployment=os.environ['AZURE_OPENAI_DEPLOYMENT'],
))
# Configure a GPT-4o deployment/API version supporting Structured Outputs.
# Close the SDK client when the application shuts down.
```

Reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Offline narrator tests: `uv run python -m unittest discover -s tests -p 'test_narrator.py' -v`.

## API orchestration

`src/api/app.py` defines `create_app(client=None, sample_path=...)` and `app`.
Startup uses FastAPI lifespan to load the sample episode into DuckDB and select
an explicitly injected client, environment-configured Azure, or the default
Mock, in that order. The sample path defaults relative to the project files,
not the process working directory. Startup failures fail explicitly. ExitStack
closes DuckDB and app-owned Azure resources on shutdown or startup failure.
Injected clients are caller-owned.

- `GET /goals` returns a sorted `list[str]` of available goal IDs.
- `GET /goals/{goal_id}/intelligence` runs repository.get, engine.analyze and
  narrator.narrate sequentially. Optional query parameters default to
  `persona=TACTICAL_ANALYST` and `language=en` and use the narrator's literals.
- `GoalIntelligenceResponse` inherits StrictModel with exactly three fields:
  episode (GoalEpisode), analysis (TacticalAnalysisResponse), narrative
  (NarrativeOutput). The validated narrative privately retains grounding context
  so nested Pydantic revalidation does not bypass the original guardrails.
- Unknown episodes return 404; invalid query values return 422. Pipeline or
  upstream failures propagate as server failures rather than silent fallbacks.
- Synchronous route handlers use FastAPI's threadpool. Repository operations
  lock the shared connection through execute/fetch; LLM calls do not hold the
  database lock. Each worker process has its own independent in-memory store.
- Azure requires nonblank AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and
  AZURE_OPENAI_DEPLOYMENT; partial configuration selects Mock.
  AZURE_OPENAI_API_VERSION defaults to 2024-10-21; no automatic dotenv loading.

Offline HTTP tests use TestClient as a context manager so lifespan executes,
with an injected Mock and temporary fixture. Coverage includes discovery,
200/404/422, localized narration, concurrent reads, OpenAPI and resource cleanup.

## Broadcast enrichment and orchestration

The legacy `/intelligence` contract is unchanged. The additive
`GET /goals/{goal_id}/broadcast?persona=TACTICAL_ANALYST&language=en&focus_player_id=P_04`
returns episode, analysis, narrative, broadcast_metrics, focus and telemetry.
Unknown goals return 404 and unsupported persona/language values return 422.

### Reproducible fictional data

`generate_mock_episodes()` returns three independent deterministic episodes:
SYNTH_GOAL_01 (quick recovery), SYNTH_GOAL_02 (central vertical breakthrough),
SYNTH_GOAL_03 (positional attack). IDs, names, coordinates and timing are stable.
The first episode retains the legacy geometry/player IDs and analytical result,
using fictional Nolan Vale, Evan Rook and Milo Arden. Existing API test name
expectations follow this fixture migration; numerical assertions remain intact.
The generator writes the first scenario to sample_goal_episode.json and the
others to episode_02.json and episode_03.json. Default API startup seeds all three
from the canonical generator in memory, so stale local files cannot expose real
player names. Custom sample_path startup still loads only that JSON fixture.
This supersedes the single-file default startup described earlier.

### Exact metric definitions

All calculations are in normalized 0–100 axes. There is no physical scale.

- Only scoring-team PASS events count for pass accuracy; the fraction is
  successful_passes / total_passes in [0,1], or null with zero attempts.
  The accuracy overlay displays the fraction multiplied by 100, unit `%`.
- The key pass is the earliest successful scoring-team pass with maximum
  static-snapshot packing (including zero); no eligible pass means null.
- pass_distance_units = hypot(end_x - start_x, end_y - start_y), unrounded,
  with explicit distance_unit=pitch_units. Its maximum is 100*sqrt(2).
- pass_difficulty = min(100, 40*distance/(100*sqrt(2)) +
  30*max(0,end_x-start_x)/100 + 30*min(packing/5,1)), unit score.
  This bounded heuristic weights normalized distance (40%), positive vertical
  gain (30%) and packing capped at five defenders (30%). It is neither measured
  difficulty nor a completion probability. Missing end_y means distance and
  difficulty are null; do not select a different key pass to hide missing data.
- duration = timestamp_goal - first chronological event.timestamp_sec.
  tempo_events_per_sec = number of all episode events / duration.
- vertical_progression_rate = max(0,last_scoring_event.start_x -
  first_scoring_event.start_x) / duration, unit pitch_units/sec. This is net
  sequence-origin progression, not ball velocity or cumulative travel distance.
- HIGH_TEMPO_CHAOS requires tempo >= 0.4 events/sec AND progression >= 4
  pitch_units/sec. Otherwise CONTROLLED_BUILDUP. Thresholds are documented
  heuristics, not observed tactical truth. Zero duration produces null rates
  and classification; no scoring events also yields null progression/class.
- timed_overlays are chronological records with event_id, timestamp_sec, label,
  value, unit, player_id, player_name and is_focus. Timestamps use the episode's
  absolute match-event clock; a replay UI subtracts the episode's first time.
  Distance/difficulty overlays appear at the pass event timestamp; sequence
  accuracy appears at the last pass timestamp. These are synthetic event replay
  markers, not inferred ball arrival times or already-rendered live overlays.
- Focus is explicitly present/absent with participating event IDs. All focused
  events get involvement overlays (value 1, score unit); pass metrics also mark
  is_focus. Unknown focus IDs are absent rather than invented players.

### Distinct agents and recovery

TacticalAnalystAgent computes facts, broadcast proxies and focus involvement once.
PersonaNarratorAgent generates only the creative proposal. GuardrailCriticAgent
validates schema/headline, scorer-or-pivot mention, internal ID leakage, and a
mandatory focus-name mention when that player participated. It records the exact
failure, hands off to the narrator, and passes critic_feedback in the second
request context plus a repair instruction. There are at most two LLM calls.
After two rejections the critic constructs and validates a deterministic fallback
that includes required and focus names. Fallback validation failure propagates;
programming errors are not disguised as creative failures.

OrchestrationState is typed and per request. Facts are computed before generation;
clients receive a deep copy of context so their mutations cannot change evidence.
telemetry contains actual handoffs, generation attempts (excluding fallback),
critic_feedback, measured latency_ms and SUCCESS/RECOVERED/DEGRADED_FALLBACK status.
Latency covers orchestration, not HTTP transport/repository lookup. Mock timing
is not an Azure latency estimate. Refusals, validation failures and sanitized
transient provider failures enter bounded recovery/fallback. Authentication,
configuration and programming errors propagate, as detailed below.
The critic implements specified syntactic/name checks, not universal semantic
truth verification of free-form narrative.

## Broadcast Studio UI (Step 5)

### Tactical evidence v1

`TacticalEngine.analyze_with_evidence()` returns the existing four-field analysis
plus `TacticalEvidence`. `analyze()` retains the existing return type and shape.
Broadcast alone exposes optional `tactical_evidence` (default null for older JSON),
with literal version `tactical-evidence-v1`. The legacy intelligence endpoint and
canonical episode/analysis schemas gain no fields.

Evidence contains:

- `scoring_team`, `key_pass_event_id` and chronological `passes`: successful
  scoring-team event IDs, absolute timestamps, authors, origin/destination X,
  counted defender IDs and packing scores. The shared strict-X helper supplies
  both tactical and broadcast calculations. The zero-packing key remains selected,
  while breakdown_zone stays null, as before.
- `inferred_connections`: source pass event ID, immediately following event ID,
  passer and inferred recipient IDs. Every contributing pass is traceable even
  when repeated edges collapse in the DiGraph. No recipient is inferred across
  an intervening rival event or a self-loop.
- `pivot_scores`: existing NetworkX unweighted normalized directed betweenness
  scores, dimensionless in [0,1]. For n > 2 the normalization factor is
  1/((n-1)(n-2)); with fewer nodes all intermediary scores are zero. Values are
  serialized unrounded. `pivot_tied_player_ids` lists all exact maximum-score
  candidates in chronological first-seen order. A zero-score tie is a selection
  rule, not evidence that a player is an outstanding connector.
- `cause_rule`: SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS, PACKING_AT_LEAST_3 or
  DEFAULT_POSITIONAL, alongside `first_event_id` and `duration_sec`. Failed/rival
  recoveries do not qualify; the recovery rule still precedes packing and includes
  the exact ten-second boundary. `limitations` describes the static geometry,
  inferred recipients and heuristic labels in English.

The analyst computes evidence once before narration. A deep copy is included
in creative context; retry, client mutation and fallback cannot rewrite it.
The studio's **Why these results?** expander presents full-episode evidence,
including at earlier replay positions, without recomputing backend analysis.
Older APIs report evidence unavailable. Accuracy cards and goal summary display
successful/attempted scoring-team passes alongside the percentage. Difficulty
keeps its original formula, units and missing-Y behavior.

Offline regression cases include mixed-team events, a rival event interrupting
recipient inference, failed/rival recoveries, normalized AWAY attacks, failed
passes in the accuracy denominator, no eligible passes, zero-centrality ties,
equal timestamps, bilingual narration, retry isolation and old JSON parsing.

### Studio behavior

Launch with `uv run streamlit run src/ui/app.py`. Local mode runs DuckDB and the
orchestrator in process. `API_BASE_URL` enables the existing API adapter; simulated
failures always use a local injectable client. Tests remain offline.

The header holds Broadcast studio and Help. Choose a play and six full-episode
metrics are global. Key Events, the pitch and on-screen facts form the tactical
domain. Persona, language and focus controls sit above the editorial narrative;
Agent behavior sits above agent telemetry. There is no sidebar, slider, autoplay
or regeneration button. Event jumps reuse the narrative; personalization preserves
the chosen offset; changing episodes resets to the complete sequence.

The clock is relative to the earliest event. Filtering includes only reached
events and overlays; the latest reached event is active. A final goal summary
shows duration, accuracy, maximum packing and the final shooter. Old overlays
remain in a collapsed expander. Handoffs show actual attempts, recovery, fallback
and critic feedback, not a simulated live processing animation.

Dark broadcast cards use the system San Francisco font stack, visible focus
outlines and explicit labels. HTML legends reflow outside Plotly to avoid overlap.
Tablet viewports up to 1180px stack domains at full width; narrower local containers
reflow selectors and agent stages. Phone milestones form a 2x2 grid. Card padding
and explicit flex gaps keep telemetry and handoffs separated.

### Optional synthetic reconstruction v1

`GoalEpisode`, `TacticalAnalysisResponse`, and the three-key intelligence response
are unchanged. `BroadcastResponse.reconstruction` is optional and defaults to null
for legacy responses. It contains a literal version `synthetic-reconstruction-v1`,
source `AUTHORED_SYNTHETIC`, offside_assessment `NOT_ASSESSED`, and `frames`.
Each frame has an event_id, matching absolute timestamp_sec, eleven opponent
positions (one goalkeeper), and every participating attacker's position.
Positions contain player_id, normalized x/y and OUTFIELD/GOALKEEPER role.

Validation requires exactly one frame per event, no duplicate IDs, stable opponent
and goalkeeper identities, all known participating attackers, and current-actor
coordinates equal to the event's recorded origin. Coordinates remain 0-100
pitch_units. No frame is interpolated, no ball-flight timing is assumed, and
no offside verdict is calculated.

The generator authors frames only for an exact canonical synthetic episode.
Unknown or modified episodes receive no invented reconstruction. Each frame uses
a defensive formation with an authored deep cover player and goalkeeper, plus
plausible positions for known attackers before their recorded actions. These are
illustrations, not observed tracking or a physics simulation. Episode pass endpoints
are destinations, not player positions or evidence of ball arrival at that timestamp.
Separate `*_reconstruction.json` exports preserve the original episode files.

Default API seeds and local UI requests attach these frames to broadcast responses.
Custom sample/API episodes without enrichment keep the legacy snapshot view.
At a selected event, the pitch renders that frame's opponents, goalkeeper and
participating attackers. The focused attacker has a blue ring. Future frames
are never displayed. The UI always labels this view **Synthetic reconstruction ·
Offside not assessed**.

Packing, key-pass selection and difficulty still use `defenders_snapshot` only.
Its five reference defenders remain unchanged. Crosses expose that static evidence
only at the key-pass milestone, visibly distinguished from the event-time circles
and goalkeeper square. The synthetic frames cannot enter the tactical engine or
alter the immutable narrative breakdown. The narrative receives the original
engine/event context, not the authored reconstruction.

Tests cover reproducibility across all scenarios, strict frame validation,
clock boundaries, player positions, optional legacy parsing, metric invariance,
and API compatibility. Run the complete suite with
`uv run python -W error -m unittest discover -s tests -v`.


## Pre-Azure reliability baseline

### Event-grounded creative checks

Grounding context now includes a separate copy of chronological episode events
and `duration_sec`. These facts are prepared before generation and kept private;
no fields are added to `CreativeOutput`, `NarrativeOutput` or legacy success JSON.
The existing headline and commentary fields are audited separately so a pattern
cannot accidentally span their boundary.

The audit adds bounded English/Spanish checks:

- Capitalized multiword names in recognized actor or recipient positions must
  match an episode name. Generic team/zone phrases, discourse prefixes, source
  accents, apostrophes, hyphens and digits are preserved. This is a contextual
  pattern check, not general named-entity recognition.
- Recognized carry, shooting, possession-recovery, completed-pass and passes-to
  claims require matching events by that author. Possession won and completed
  passes require successful events; an unsuccessful shot can support a shot
  mention without supporting a goal claim.
- Explicit passes-to claims require an immediately adjacent same-team event
  after a successful pass, with a different player ID. Rival events cannot be
  skipped. This checks consistency with the recipient inference proxy, not
  physical evidence of receipt.
- Selected passive scorer statements and explicit player-role constructions
  must identify the known scorer, pivot or key-pass author.
- Recognized completion counts match successful/attempted passes. A named player
  is checked against their own events; otherwise the scoring-team counts apply.
  Labelled sequence duration matches the episode clock. Percentages must match
  pass accuracy; difficulty stays a score. Supported numeric words remain 0–20.
- Explicit ball/shot speed labels and recognized keeper-beating dribbles are
  rejected because the event contract does not establish those measurements or
  actions. Authored reconstruction frames cannot supply narrative evidence.

The original `Zorlan Phantom` example is rejected in direct narration and enters
the existing feedback-driven retry in broadcast. A second rejection still emits
the validated deterministic fallback. Facts and contracts are not recomputed or
rewritten to accept a draft. No extra model calls, online dependency, language
detector or semantic verifier are introduced.

Adversarial offline tests cover unknown actors/recipients, wrong action authors,
failed recoveries, false passing connections, passive goal attribution, numeric
scope errors and fallback. Positive cases cover truthful bilingual statements,
source-name variations and existing persona templates. Unsupported paraphrases,
lowercase/single-word invented names and arbitrary semantic claims can still
pass; these checks must not be advertised as zero hallucination.

### Provider and recovery baseline

- `agents/grounding.py` audits explicit English/Spanish claims against immutable
  request facts: maximum packing and defender counts, labelled pass metrics,
  allowed numeric values (0/1/2 decimal rounding), exact zone labels, and selected
  known-player pivot/scorer/key-pass constructions. Digit-bearing player names
  are preserved. Physical distance/speed units are rejected because no such
  measurements exist. Number words are supported from zero to twenty. Negation,
  arbitrary paraphrases, unrecognized role phrasing, invented proper names and
  broader semantic truth are not comprehensively validated; do not advertise
  zero hallucination for free creative text.
- The same Pydantic audit applies to direct narration and critic validation.
  Broadcast metrics are passed into narrator preparation once; facts are never
  recomputed to fit rejected drafts. Invalid explicit claims trigger one real
  repair attempt, then the existing deterministic fallback.
- `ExecutionTelemetry.generation_provider` and `narrative_provider` distinguish
  OFFLINE_MOCK, AZURE_OPENAI, OFFLINE_FALLBACK, CUSTOM and UNKNOWN. Defaults preserve
  parsing of older broadcast responses. These fields are added only to enriched
  telemetry; the legacy three-key intelligence contract remains intact.
- Azure adapter exceptions map timeouts, connection failures, 429, transient
  408/409/5xx and truncated output to sanitized recoverable errors. Production SDK
  timeout is 10 seconds, SDK max_retries is zero, output cap is 600 tokens and
  orchestration allows two calls maximum. There are no blocking backoff sleeps.
  Nonrecoverable authentication/configuration and system errors propagate.
  `/intelligence` returns 503 on recoverable provider unavailability; `/broadcast`
  may recover or return a valid OFFLINE_FALLBACK narrative with degraded status.
- Six offline persona/language variants use reviewed event-grounded templates,
  correct sentence joining and singular/plural defender forms. The first action,
  key-pass author, pivot and scorer remain distinct. No crowd reactions, player
  intentions or additional match events are inferred from missing data.
- Python is constrained to the tested 3.14 minor and `.python-version` selects
  3.14.2. Streamlit/OpenAI lower bounds match the tested APIs; `uv sync --locked`
  reproduces the lockfile. Tests generate their own canonical fixtures and require
  no ignored `data/raw` files. `scripts/check_startup.py` checks real loopback
  server startup without Azure credentials or persistent child processes.
