"""Optional synthetic visual context; never tracking evidence or an offside verdict."""
from typing import Literal

from pydantic import Field, model_validator

from src.analytics.schemas import Coordinate, GoalEpisode, ID, StrictModel, Time


class ReconstructionPosition(StrictModel):
    player_id: ID
    x: Coordinate
    y: Coordinate
    role: Literal['OUTFIELD', 'GOALKEEPER'] = 'OUTFIELD'


class ReconstructionFrame(StrictModel):
    event_id: ID
    timestamp_sec: Time
    opponents: list[ReconstructionPosition]
    attackers: list[ReconstructionPosition]

    @model_validator(mode='after')
    def validate_players(self):
        if len(self.opponents) != 11 or sum(p.role == 'GOALKEEPER' for p in self.opponents) != 1:
            raise ValueError('A reconstruction requires eleven opponents including one goalkeeper')
        players = self.opponents + self.attackers
        if len({p.player_id for p in players}) != len(players):
            raise ValueError('Reconstruction player IDs must be unique within a frame')
        return self


class SyntheticReconstruction(StrictModel):
    version: Literal['synthetic-reconstruction-v1'] = 'synthetic-reconstruction-v1'
    source: Literal['AUTHORED_SYNTHETIC'] = 'AUTHORED_SYNTHETIC'
    offside_assessment: Literal['NOT_ASSESSED'] = 'NOT_ASSESSED'
    frames: list[ReconstructionFrame] = Field(min_length=1)

    def validate_episode(self, episode: GoalEpisode) -> None:
        events = {e.event_id: e for e in episode.events}
        if len(self.frames) != len(events) or {f.event_id for f in self.frames} != set(events):
            raise ValueError('Reconstruction must contain exactly one frame per episode event')
        participants = {e.player_id for e in episode.events}
        roster = {p.player_id for p in self.frames[0].opponents}
        keeper_id = next(p.player_id for p in self.frames[0].opponents if p.role == 'GOALKEEPER')
        for frame in self.frames:
            event = events[frame.event_id]
            if frame.timestamp_sec != event.timestamp_sec:
                raise ValueError('Reconstruction timestamps must match their events')
            if {p.player_id for p in frame.attackers} != participants:
                raise ValueError('Reconstruction must identify all participating attackers')
            if {p.player_id for p in frame.opponents} != roster:
                raise ValueError('Reconstruction opponent roster must remain consistent')
            if next(p.player_id for p in frame.opponents if p.role == 'GOALKEEPER') != keeper_id:
                raise ValueError('The reconstructed goalkeeper must remain consistent')
            actor = next(p for p in frame.attackers if p.player_id == event.player_id)
            if (actor.x, actor.y) != (event.start_x, event.start_y):
                raise ValueError('Reconstruction actor position must match the event origin')
