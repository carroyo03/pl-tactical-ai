"""Pure replay-clock filtering and normalized-pitch plotting."""
from dataclasses import dataclass
from math import isfinite

import plotly.graph_objects as go

from src.agents.orchestrator import BroadcastResponse
from src.analytics.broadcast import TimedOverlay
from src.analytics.schemas import MatchEvent

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
        text=['Bypassed in static snapshot' if value else 'Static defender' for value in eliminated],
        hovertemplate='%{text}<br>X %{x:.1f} / Y %{y:.1f}<extra></extra>',
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
            text=[f'{event.player_name} / {event.event_type.lower()} / +{item.relative_sec:.1f}s'] * 2,
            hovertemplate='%{text}<br>X %{x:.1f} / Y %{y:.1f}<extra></extra>',
            meta={'event_id': event.event_id, 'is_key_pass': key, 'is_focus': focus, 'is_active': item.is_active},
        ))
        if key:
            figure.add_annotation(x=event.start_x, y=event.start_y, text='Key pass',
                                  showarrow=False, yshift=24, font=dict(color=AMBER, size=11))
    figure.update_layout(
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=TEXT, family='Arial, sans-serif'),
        margin=dict(l=14, r=14, t=12, b=22), height=480, showlegend=False,
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, title='Normalized pitch / attack direction →',
                   tickvals=[0, 33.3, 66.6, 100], fixedrange=True),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        uirevision='broadcast-pitch',
    )
    return figure
