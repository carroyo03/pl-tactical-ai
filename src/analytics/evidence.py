"""Optional versioned evidence for existing tactical calculations."""
from typing import Annotated, Literal

from pydantic import Field

from src.analytics.schemas import Coordinate, ID, StrictModel, Time


class PassEvidence(StrictModel):
    event_id: ID
    timestamp_sec: Time
    player_id: ID
    start_x: Coordinate
    end_x: Coordinate
    bypassed_defender_ids: list[ID]
    packing_score: Annotated[int, Field(ge=0)]


class InferredConnection(StrictModel):
    pass_event_id: ID
    next_event_id: ID
    passer_id: ID
    inferred_recipient_id: ID


class TacticalEvidence(StrictModel):
    version: Literal['tactical-evidence-v1'] = 'tactical-evidence-v1'
    scoring_team: Literal['HOME', 'AWAY']
    key_pass_event_id: ID | None
    passes: list[PassEvidence]
    inferred_connections: list[InferredConnection]
    pivot_scores: dict[str, Annotated[float, Field(ge=0, le=1)]]
    pivot_tied_player_ids: list[ID]
    cause_rule: Literal['SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS', 'PACKING_AT_LEAST_3', 'DEFAULT_POSITIONAL']
    first_event_id: ID
    duration_sec: Time
    limitations: list[str]
