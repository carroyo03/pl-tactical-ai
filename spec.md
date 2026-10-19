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

For each successful PASS, count defenders with
`start_x < defender.x < end_x`. Exclude endpoints; lateral/backward passes
score zero. `sequence_packing_score` is MAX of per-pass scores (default zero),
never their sum. Equal positive scores choose the earliest chronological pass.
With no positive score, breakdown_zone is null.

The same static snapshot is used for each pass. MAX avoids accumulating
repeated counts, but is still a static approximation, not time-aligned tracking.
The input snapshot has no timestamp; no timing is inferred from mock comments.

### Pass graph

NetworkX DiGraph: for each successful PASS, connect its author to the player of
its immediately following event in the full sorted sequence, including SHOT.
This infers the recipient because the input has no explicit recipient field.
Only connect different players of the same team. A terminal pass has no edge.
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

1. First chronological event is RECOVERY and
   `timestamp_goal - first.timestamp_sec <= 10`:
   `Quick transition after recovery`.
2. Otherwise, sequence_packing_score >= 3:
   `Central breakthrough through a vertical pass`.
3. Otherwise: `Positional attack`.

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
