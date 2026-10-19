"""Strict canonical JSON contracts."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Coordinate = Annotated[float, Field(ge=0, le=100)]
Time = Annotated[float, Field(ge=0)]
ID = Annotated[str, Field(min_length=1)]
Zone = Literal['Defensive Third', 'Middle Third', 'Attacking Third']
Cause = Literal['Quick transition after recovery', 'Central breakthrough through a vertical pass', 'Positional attack']


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class MatchEvent(StrictModel):
    event_id: ID
    match_id: ID
    timestamp_sec: Time
    period: Literal[1, 2]
    team: Literal['HOME', 'AWAY']
    player_id: ID
    player_name: ID
    event_type: Literal['PASS', 'CARRY', 'RECOVERY', 'SHOT', 'DEFENSIVE_DUEL']
    start_x: Coordinate
    start_y: Coordinate
    end_x: Coordinate | None = None
    end_y: Coordinate | None = None
    is_successful: bool

    @model_validator(mode='after')
    def validate_pass(self):
        if self.event_type == 'PASS' and self.end_x is None:
            raise ValueError('PASS requires end_x')
        return self


class DefenderPosition(StrictModel):
    player_id: ID
    x: Coordinate
    y: Coordinate


class GoalEpisode(StrictModel):
    goal_id: ID
    match_id: ID
    timestamp_goal: Time
    scoring_team: Literal['HOME', 'AWAY']
    conceding_team: Literal['HOME', 'AWAY']
    events: Annotated[list[MatchEvent], Field(min_length=1)]
    defenders_snapshot: list[DefenderPosition]

    @model_validator(mode='after')
    def validate_episode(self):
        if self.scoring_team == self.conceding_team:
            raise ValueError('Scoring and conceding teams must differ')
        if any(e.match_id != self.match_id for e in self.events):
            raise ValueError('Events must belong to episode match')
        if any(e.timestamp_sec > self.timestamp_goal for e in self.events):
            raise ValueError('Events cannot occur after goal')
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError('Duplicate event_id')
        if len({d.player_id for d in self.defenders_snapshot}) != len(self.defenders_snapshot):
            raise ValueError('Duplicate defender player_id')
        return self


class TacticalAnalysisResponse(StrictModel):
    sequence_packing_score: Annotated[int, Field(ge=0)]
    tactical_pivot: ID | None
    breakdown_zone: Zone | None
    tactical_cause: Cause
