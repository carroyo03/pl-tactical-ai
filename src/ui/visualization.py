"""Pure replay-clock filtering and normalized-pitch plotting."""
from dataclasses import dataclass
from math import isfinite
from html import escape

import plotly.graph_objects as go

from src.agents.orchestrator import BroadcastResponse
from src.analytics.broadcast import TimedOverlay
from src.analytics.schemas import MatchEvent

SYSTEM_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, "Segoe UI", sans-serif'
BACKGROUND = '#090A0F'
PANEL = '#11131A'
BLUE = '#76ADFF'
AMBER = '#E8B86D'
TEXT = '#E8ECF4'


@dataclass(frozen=True)
class ReplayEvent:
    event: MatchEvent
    relative_sec: float
    is_active: bool


@dataclass(frozen=True)
class ReplayOverlay:
    overlay: TimedOverlay
    relative_sec: float
    is_active: bool


@dataclass(frozen=True)
class ReplayFrame:
    replay_offset_sec: float
    duration: float
    events: list[ReplayEvent]
    timed_overlays: list[ReplayOverlay]


def filter_synchronized_overlays(
    broadcast_response: BroadcastResponse, replay_offset_sec: float,
) -> ReplayFrame:
    """Clamp finite offsets; include exact boundaries. Active means latest reached event."""
    if not isfinite(replay_offset_sec):
        raise ValueError('Replay offset must be finite')
    episode = broadcast_response.episode
    events = sorted(episode.events, key=lambda event: event.timestamp_sec)
    start = events[0].timestamp_sec
    duration = episode.timestamp_goal - start
    offset = max(0.0, min(float(replay_offset_sec), duration))
    # Compare on the absolute clock to avoid subtraction noise at exact boundaries.
    cutoff = start + offset
    reached = [e for e in events if e.timestamp_sec <= cutoff]
    active_time = reached[-1].timestamp_sec
    return ReplayFrame(
        offset, duration,
        [ReplayEvent(e, e.timestamp_sec - start, e.timestamp_sec == active_time) for e in reached],
        [ReplayOverlay(o, o.timestamp_sec - start, o.timestamp_sec == active_time)
         for o in sorted(broadcast_response.broadcast_metrics.timed_overlays, key=lambda o: o.timestamp_sec)
         if o.timestamp_sec <= cutoff],
    )


@dataclass(frozen=True)
class EventMilestone:
    event_id: str
    relative_sec: float
    label: str
    player_name: str
    is_current: bool
    is_reached: bool


@dataclass(frozen=True)
class GoalSequenceSummary:
    duration_sec: float
    pass_accuracy: float | None
    maximum_packing: int
    final_shooter: str | None


def build_event_timeline(response: BroadcastResponse, replay_offset_sec: float) -> list[EventMilestone]:
    """All chronological milestones, including future steps; only reached steps are current."""
    frame = filter_synchronized_overlays(response, replay_offset_sec)
    start = min(e.timestamp_sec for e in response.episode.events)
    current_ids = {item.event.event_id for item in frame.events if item.is_active}
    reached_ids = {item.event.event_id for item in frame.events}
    milestones = []
    for event in sorted(response.episode.events, key=lambda item: item.timestamp_sec):
        goal_shot = (event.event_type == 'SHOT' and event.is_successful
                     and event.team == response.episode.scoring_team
                     and event.timestamp_sec == response.episode.timestamp_goal)
        label = ('Goal shot' if goal_shot else 'Key pass' if event.event_id == response.broadcast_metrics.key_pass_event_id
                 else event.event_type.replace('_', ' ').capitalize())
        milestones.append(EventMilestone(event.event_id, event.timestamp_sec - start,
                                        label, event.player_name, event.event_id in current_ids,
                                        event.event_id in reached_ids))
    return milestones


def build_goal_summary(response: BroadcastResponse, replay_offset_sec: float) -> GoalSequenceSummary | None:
    """Consolidated facts appear only when the goal timestamp has been reached."""
    frame = filter_synchronized_overlays(response, replay_offset_sec)
    start = min(event.timestamp_sec for event in response.episode.events)
    if start + frame.replay_offset_sec < response.episode.timestamp_goal:
        return None
    shooters = [item.event.player_name for item in frame.events
                if item.event.event_type == 'SHOT' and item.event.is_successful
                and item.event.team == response.episode.scoring_team
                and item.event.timestamp_sec == response.episode.timestamp_goal]
    return GoalSequenceSummary(frame.duration, response.broadcast_metrics.pass_accuracy,
                               response.analysis.sequence_packing_score,
                               shooters[0] if len(shooters) == 1 else None)


def build_pitch_figure(
    broadcast_response: BroadcastResponse, replay_offset_sec: float | None = None,
) -> go.Figure:
    """Full sequence by default; geometry and defensive colors never anticipate the key pass."""
    response = broadcast_response
    first = min(e.timestamp_sec for e in response.episode.events)
    frame = filter_synchronized_overlays(
        response, response.episode.timestamp_goal - first if replay_offset_sec is None else replay_offset_sec,
    )
    figure = go.Figure()
    figure.add_shape(type='rect', x0=0, x1=100, y0=0, y1=100,
                     line=dict(color='#657083', width=1), fillcolor='#101A21', layer='below')
    for x in (33.3, 66.6):
        figure.add_shape(type='line', x0=x, x1=x, y0=0, y1=100,
                         line=dict(color='#3B4554', dash='dot'), layer='below')
    figure.add_shape(type='line', x0=50, x1=50, y0=0, y1=100, line=dict(color='#3B4554'))
    figure.add_shape(type='circle', x0=40, x1=60, y0=40, y1=60, line=dict(color='#3B4554'))
    for x0, x1 in ((0, 16), (84, 100)):
        figure.add_shape(type='rect', x0=x0, x1=x1, y0=22, y1=78, line=dict(color='#3B4554'))
    visible_key = next((item.event for item in frame.events
                        if item.event.event_id == response.broadcast_metrics.key_pass_event_id), None)
    defenders = response.episode.defenders_snapshot
    eliminated = [bool(visible_key and visible_key.start_x < d.x < visible_key.end_x) for d in defenders]
    figure.add_trace(go.Scatter(
        x=[d.x for d in defenders], y=[d.y for d in defenders], mode='markers',
        name='Defensive snapshot', marker=dict(size=12, symbol='x',
        color=['#E58F94' if value else '#7A8496' for value in eliminated]),
        text=[escape(d.player_id) for d in defenders],
        customdata=[['Bypassed in key pass' if value else 'Active in key-pass comparison' if visible_key
                     else 'Snapshot / key pass not reached'] for value in eliminated],
        hovertemplate='<b>%{text}</b><br>%{customdata[0]}<br>X %{x:.1f} / Y %{y:.1f} pitch_units<extra></extra>',
        meta={'kind': 'defenders', 'bypassed': eliminated},
    ))
    for item in frame.events:
        event = item.event
        key = event.event_id == response.broadcast_metrics.key_pass_event_id
        focus = response.focus.participated and event.player_id == response.focus.player_id
        color = AMBER if key else BLUE if focus else '#CDD5E1'
        figure.add_trace(go.Scatter(
            x=[event.start_x, event.end_x if event.end_x is not None else event.start_x],
            y=[event.start_y, event.end_y if event.end_y is not None else event.start_y],
            mode='lines+markers', name=f'{event.player_name}: {event.event_type.lower()}',
            line=dict(color=color, width=5 if key else 3, dash='dot' if not event.is_successful else 'solid'),
            marker=dict(size=[13 if focus else 8, 7], color=color,
                        symbol=['circle-open' if focus else 'circle', 'diamond']),
            opacity=1.0 if item.is_active or key or focus else .5,
            text=[f'<b>{escape(event.player_name)}</b><br>{escape(event.event_type.replace("_", " ").capitalize())}'
                  f' / +{item.relative_sec:.1f}s'] * 2,
            customdata=[['Origin'], ['Destination' if event.end_x is not None and event.end_y is not None
                                    else 'Destination unavailable; marker stays at known coordinates']],
            hovertemplate='%{text}<br>%{customdata[0]}<br>X %{x:.1f} / Y %{y:.1f} pitch_units<extra></extra>',
            meta={'event_id': event.event_id, 'is_key_pass': key, 'is_focus': focus, 'is_active': item.is_active},
        ))
        if key:
            figure.add_annotation(x=event.start_x, y=event.start_y, text='Key pass',
                                  showarrow=False, yshift=24, font=dict(color=AMBER, size=11))
    # Paper-space legend preserves trace contracts and does not add fabricated pitch data.
    for x, label, color in [
        (0.0, '● Key pass', AMBER), (.26, '◎ Focused player', BLUE),
        (.53, '✕ Bypassed defender', '#E58F94'), (.81, '✕ Active defender', '#A6B0C3'),
    ]:
        figure.add_annotation(x=x, y=1.09, xref='paper', yref='paper', text=label,
                              xanchor='left', showarrow=False, font=dict(size=11, color=color))
    figure.update_layout(
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=TEXT, family=SYSTEM_FONT),
        margin=dict(l=14, r=26, t=60, b=36), height=480, showlegend=False,
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, title='Normalized pitch / attack direction →',
                   tickvals=[0, 33.3, 66.6, 100], fixedrange=True),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        uirevision='broadcast-pitch',
    )
    return figure
