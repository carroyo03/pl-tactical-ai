"""Broadcast proxies on normalized pitch axes, never physical ball speeds."""
from math import hypot, sqrt
from typing import Annotated, Literal

from pydantic import Field

from src.analytics.schemas import GoalEpisode, ID, StrictModel, Time
from src.analytics.sequence import bypassed_defender_ids, scoring_passes

Nonnegative = Annotated[float, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=100)]


class FocusParticipation(StrictModel):
    player_id: ID | None = None
    player_name: ID | None = None
    participated: bool = False
    event_ids: list[str] = Field(default_factory=list)


class TimedOverlay(StrictModel):
    event_id: ID
    timestamp_sec: Time
    label: str
    value: float
    unit: Literal['pitch_units', '%', 'score']
    player_id: ID
    player_name: ID
    is_focus: bool = False


class BroadcastMetrics(StrictModel):
    key_pass_event_id: ID | None
    pass_distance_units: Nonnegative | None
    distance_unit: Literal['pitch_units'] = 'pitch_units'
    pass_difficulty: Score | None
    pass_accuracy: Annotated[float, Field(ge=0, le=1)] | None
    successful_passes: Annotated[int, Field(ge=0)]
    total_passes: Annotated[int, Field(ge=0)]
    tempo_events_per_sec: Nonnegative | None
    vertical_progression_rate: Nonnegative | None
    progression_unit: Literal['pitch_units/sec'] = 'pitch_units/sec'
    tempo_classification: Literal['HIGH_TEMPO_CHAOS', 'CONTROLLED_BUILDUP'] | None
    timed_overlays: list[TimedOverlay]


def compute_broadcast(episode: GoalEpisode, focus_player_id: str | None = None) -> tuple[BroadcastMetrics, FocusParticipation]:
    events = sorted(episode.events, key=lambda event: event.timestamp_sec)
    involvement = [e for e in events if e.player_id == focus_player_id]
    focus = FocusParticipation(
        player_id=focus_player_id, player_name=involvement[0].player_name if involvement else None,
        participated=bool(involvement), event_ids=[e.event_id for e in involvement],
    )
    passes = scoring_passes(episode)
    successes = [e for e in passes if e.is_successful]
    packing = {e.event_id: len(bypassed_defender_ids(episode, e))
               for e in successes}
    key = max(successes, key=lambda e: packing[e.event_id], default=None)
    distance = None
    difficulty = None
    overlays = []
    for event in successes:
        if event.end_y is not None:
            length = hypot(event.end_x - event.start_x, event.end_y - event.start_y)
            rating = min(100.0, 40 * length / (100 * sqrt(2))
                         + 30 * max(0.0, event.end_x - event.start_x) / 100
                         + 30 * min(packing[event.event_id] / 5, 1.0))
            if event is key:
                distance, difficulty = length, rating
            for label, value, unit in [('Pass distance', length, 'pitch_units'),
                                       ('Pass difficulty', rating, 'score')]:
                overlays.append(TimedOverlay(
                    event_id=event.event_id, timestamp_sec=event.timestamp_sec,
                    label=label, value=value, unit=unit, player_id=event.player_id,
                    player_name=event.player_name, is_focus=event.player_id == focus_player_id,
                ))
    accuracy = len(successes) / len(passes) if passes else None
    if passes:
        event = passes[-1]
        overlays.append(TimedOverlay(
            event_id=event.event_id, timestamp_sec=event.timestamp_sec,
            label='Sequence pass accuracy', value=accuracy * 100, unit='%',
            player_id=event.player_id, player_name=event.player_name,
            is_focus=event.player_id == focus_player_id,
        ))
    for event in involvement:
        overlays.append(TimedOverlay(
            event_id=event.event_id, timestamp_sec=event.timestamp_sec,
            label='Focused player involvement', value=1.0, unit='score',
            player_id=event.player_id, player_name=event.player_name, is_focus=True,
        ))
    duration = episode.timestamp_goal - events[0].timestamp_sec
    scoring = [e for e in events if e.team == episode.scoring_team]
    tempo = len(events) / duration if duration > 0 else None
    progression = (max(0.0, scoring[-1].start_x - scoring[0].start_x) / duration
                   if duration > 0 and scoring else None)
    classification = None
    if tempo is not None and progression is not None:
        classification = ('HIGH_TEMPO_CHAOS' if tempo >= 0.4 and progression >= 4.0
                          else 'CONTROLLED_BUILDUP')
    return BroadcastMetrics(
        key_pass_event_id=key.event_id if key else None,
        pass_distance_units=distance, pass_difficulty=difficulty, pass_accuracy=accuracy,
        successful_passes=len(successes), total_passes=len(passes),
        tempo_events_per_sec=tempo, vertical_progression_rate=progression,
        tempo_classification=classification,
        timed_overlays=sorted(overlays, key=lambda overlay: overlay.timestamp_sec),
    ), focus
