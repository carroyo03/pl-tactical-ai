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
    current_event = frame.events[-1].event
    show_reference = response.reconstruction is None or current_event.event_id == response.broadcast_metrics.key_pass_event_id
    defenders = response.episode.defenders_snapshot
    eliminated = [bool(visible_key and visible_key.start_x < d.x < visible_key.end_x) for d in defenders]
    figure.add_trace(go.Scatter(
        x=[d.x for d in defenders], y=[d.y for d in defenders], mode='markers',
        name='Packing reference snapshot', visible=show_reference, marker=dict(size=12, symbol='x',
        color=['#E58F94' if value else '#7A8496' for value in eliminated]),
        text=[escape(d.player_id) for d in defenders],
        customdata=[['Bypassed in key pass / static packing reference' if value else 'Active in key-pass comparison' if visible_key
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
    if response.reconstruction is not None:
        selected = next(f for f in response.reconstruction.frames if f.event_id == current_event.event_id)
        relative = selected.timestamp_sec - first
        outfield = [p for p in selected.opponents if p.role == 'OUTFIELD']
        goalkeeper = [p for p in selected.opponents if p.role == 'GOALKEEPER']
        names = {e.player_id: e.player_name for e in response.episode.events}
        for positions, kind, label, symbol, color in [
            (outfield, 'reconstructed_opponents', 'Synthetic opponents', 'circle-open', '#A6B0C3'),
            (goalkeeper, 'reconstructed_goalkeeper', 'Synthetic goalkeeper', 'square', '#79C7B4'),
            (selected.attackers, 'reconstructed_attackers', 'Participating attackers', 'circle', '#E8ECF4'),
        ]:
            focused = [response.focus.participated and p.player_id == response.focus.player_id for p in positions]
            figure.add_trace(go.Scatter(
                x=[p.x for p in positions], y=[p.y for p in positions], mode='markers', name=label,
                marker=dict(size=[14 if focused[i] else 10 for i in range(len(positions))],
                            symbol=['circle-open' if focused[i] else symbol for i in range(len(positions))],
                            color=[BLUE if focused[i] else color for i in range(len(positions))], line=dict(width=2)),
                text=[escape(names.get(p.player_id, p.player_id)) for p in positions],
                customdata=[[label, f'+{relative:.1f}s'] for p in positions],
                hovertemplate='<b>%{text}</b><br>%{customdata[0]} / %{customdata[1]}<br>'
                              'X %{x:.1f} / Y %{y:.1f} pitch_units<br>Synthetic reconstruction<extra></extra>',
                meta=dict(kind=kind, event_id=selected.event_id, timestamp_sec=selected.timestamp_sec,
                          source='AUTHORED_SYNTHETIC', is_focus=any(focused)),
            ))
    # Paper-space legend supports standalone figures; the studio renders reflowing HTML.
    legend = [(0.0, 1.09, '● Key pass', AMBER), (.26, 1.09, '◎ Focused player', BLUE),
              (.53, 1.09, '✕ Bypassed defender', '#E58F94'), (.81, 1.09, '✕ Active defender', '#A6B0C3')]
    if response.reconstruction is not None:
        legend = [(0.0, 1.24, '● Key pass', AMBER), (.52, 1.24, '◎ Focused player', BLUE),
                  (0.0, 1.15, '○ Opponents / ■ goalkeeper', '#79C7B4'), (.52, 1.15, '● Participating attackers', TEXT),
                  (0.0, 1.06, '✕ Bypassed reference', '#E58F94'), (.52, 1.06, '✕ Other packing reference', '#A6B0C3')]
    for x, y, label, color in legend:
        figure.add_annotation(x=x, y=y, xref='paper', yref='paper', text=label,
                              xanchor='left', showarrow=False, font=dict(size=11, color=color))
    figure.update_layout(
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=TEXT, family=SYSTEM_FONT),
        margin=dict(l=14, r=26, t=100 if response.reconstruction is not None else 60, b=36), height=480, showlegend=False,
        xaxis=dict(range=[0, 100], showgrid=False, zeroline=False, title='Normalized pitch / attack direction →',
                   tickvals=[0, 33.3, 66.6, 100], fixedrange=True),
        yaxis=dict(range=[0, 100], showgrid=False, zeroline=False, showticklabels=False, fixedrange=True),
        uirevision='broadcast-pitch',
    )
    return figure
