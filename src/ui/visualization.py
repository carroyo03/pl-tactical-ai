"""Pure replay-clock filtering and normalized-pitch plotting."""
from dataclasses import dataclass
from math import isfinite
from html import escape
import re

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


def build_analysis_explanations(response: BroadcastResponse) -> list[tuple[str, str]]:
    """Readable Markdown sections from existing backend evidence; no new analysis."""
    evidence = response.tactical_evidence
    if evidence is None:
        return []

    def plain(value: str) -> str:
        # Source names and IDs remain text, never Markdown links or formatting.
        return re.sub(r'([\\`*_{}\[\]()#+!|>~])', r'\\\1', escape(value))

    events = {event.event_id: event for event in response.episode.events}
    names = {event.player_id: event.player_name for event in response.episode.events}
    defenders = {defender.player_id: defender for defender in response.episode.defenders_snapshot}
    key = next((item for item in evidence.passes if item.event_id == evidence.key_pass_event_id), None)
    explanations = []
    if key is None:
        explanations.append(('Why this pass?',
            '**No completed scoring-team pass is available.**\n\n'
            'Packing is zero. A highlighted pass cannot be selected.'))
        explanations.append(('Where did the breakthrough start?',
            '**No breakdown zone is assigned.**\n\n'
            'A zone requires a completed scoring-team pass with positive packing.'))
    else:
        counted = '\n'.join(
            f'- The reference defender **{plain(player)}** is positioned at **X={defenders[player].x:g}**, '
            'between the start and end of this pass.'
            for player in key.bypassed_defender_ids
        ) or 'No reference defenders lie strictly between the start and end of this pass.'
        comparisons = '\n'.join(
            f'- {plain(names[item.player_id])} completes a pass that bypasses **{item.packing_score} '
            f'{"reference defender" if item.packing_score == 1 else "reference defenders"}** '
            f'in the static snapshot. This pass is recorded as {plain(item.event_id)}.'
            for item in evidence.passes)
        offset = key.timestamp_sec - min(event.timestamp_sec for event in response.episode.events)
        explanations.append(('Why this pass?',
            f'**The pass by {plain(names[key.player_id])} is highlighted because it has the highest '
            f'packing score in this episode: {key.packing_score}.**\n\n'
            f'This pass is completed **{offset:g} seconds after the episode begins**. '
            f'Its origin is recorded at **X={key.start_x:g}** and its destination at **X={key.end_x:g}** on the normalized pitch. '
            'Defender references are counted when their X positions lie strictly between those two points.\n\n'
            '**These defenders contribute to the score:**\n\n'
            f'{counted}\n\n'
            '**The completed passes are compared as follows:**\n\n'
            f'{comparisons}\n\n'
            'The pass with the highest score is selected. If several passes share that score, '
            'the earliest one in the episode is selected. A defender at either endpoint is excluded.\n\n'
            f'*The selected event is recorded as {plain(key.event_id)} at {key.timestamp_sec:g} seconds '
            'on the match clock. The score compares one static snapshot; it does not establish an assist '
            'or show how the defenders moved.*'))
        zone_result = response.analysis.breakdown_zone or 'Unavailable'
        explanations.append(('Where did the breakthrough start?',
            (f'**The highlighted pass begins in the {zone_result.lower()}.**\n\n'
             if key.packing_score > 0 else
             '**A breakdown zone cannot be assigned because the packing score is zero.**\n\n')
            + f'The pass starts at **X={key.start_x:g}** on a pitch whose coordinates run from 0 to 100. '
            'This starting position is used to assign a zone when the packing score is positive.\n\n'
            '- The **defensive third** is assigned when the starting X is below 33.3.\n'
            '- The **middle third** is assigned when the starting X is at least 33.3 and below 66.6.\n'
            '- The **attacking third** is assigned when the starting X is at least 66.6.\n\n'
            '*This zone describes where the selected pass starts. It does not locate the receiver '
            'or establish where a defensive line was physically broken.*'))
    links = '\n'.join(
        f'- **{plain(names[link.inferred_recipient_id])} is inferred to be the receiver of the pass by {plain(names[link.passer_id])}** '
        f'because event {plain(link.next_event_id)} immediately follows the completed pass '
        f'{plain(link.pass_event_id)} and belongs to that teammate.'
        for link in evidence.inferred_connections
    ) or 'The recorded events do not provide any eligible passing connections.'
    pivot = response.analysis.tactical_pivot
    scores = '\n'.join(f'- A score of **{score:.3f}** is assigned to **{plain(names[player])}**.'
                       for player, score in evidence.pivot_scores.items())
    pivot_text = (f'**{plain(names[pivot])} is the selected connector.**\n\n'
                  'A network is built from the completed passes and their inferred receivers. '
                  'Each player is scored by how often they connect other players along the '
                  'network’s shortest routes. The player with the highest score is selected as the tactical pivot.\n\n'
                  if pivot else '**A connector cannot be selected because the network has no eligible passing connections.**\n\n')
    if len(evidence.pivot_tied_player_ids) > 1:
        pivot_text += '**The tie is resolved using the event order.** ' + ', '.join(plain(names[player]) for player in evidence.pivot_tied_player_ids) + ' share the highest score, so the player who appears first chronologically is selected.\n\n'
    if pivot is not None and evidence.pivot_scores[pivot] == 0:
        pivot_text += '**All scores are zero, so the selection comes entirely from the chronological tie-break.** The data does not identify a standout connector.\n\n'
    if scores:
        pivot_text += '**Normalized betweenness scores**\n\nThese dimensionless scores range from 0 to 1.\n\n' + scores + '\n\n'
    explanations.append(('Why this connector?', pivot_text + '**The events support these inferred connections:**\n\n' + links + '\n\n'
        '*Receivers are not identified explicitly in the input. Each receiver is inferred from the immediately '
        'following event, and that inference is interrupted by a rival event. Multiple passes between the same '
        'two players are represented by a single connection in this unweighted network.*'))
    first = events[evidence.first_event_id]
    rules = {
        'SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS': 'The first event is a successful scoring-team recovery and the goal follows within ten seconds.',
        'PACKING_AT_LEAST_3': 'The recovery rule does not apply and maximum static packing is at least three. The legacy label does not prove a central channel.',
        'DEFAULT_POSITIONAL': 'Neither the recovery rule nor the packing threshold applies. Positional attack is a fallback label, not measured possession control.',
    }
    explanations.append(('Why this tactical label?',
        f'**This episode is classified as “{response.analysis.tactical_cause}”.**\n\n'
        f'{rules[evidence.cause_rule]}\n\n'
        f'The episode begins with {plain(first.player_name)} performing a '
        f'{first.event_type.replace("_", " ").lower()} for the {first.team} team. '
        f'The event is recorded as {"successful" if first.is_successful else "unsuccessful"}, '
        f'and the goal follows **{evidence.duration_sec:g} seconds later**.\n\n'
        '**The first matching rule is applied:**\n\n'
        '1. A **quick transition** is assigned when the first event is a successful recovery '
        'by the scoring team and the goal follows within ten seconds.\n'
        '2. Otherwise, the **central breakthrough** label is assigned when the maximum packing score is at least three.\n'
        '3. If neither condition applies, **positional attack** is assigned as the fallback label.\n\n'
        '*This is a rule-based classification, not proof of why the goal happened.*'))
    metrics = response.broadcast_metrics
    accuracy_text = (f'**The scoring team completes {metrics.successful_passes} of its '
                     f'{metrics.total_passes} attempted passes, giving an accuracy of {metrics.pass_accuracy * 100:.0f}%.**'
                     if metrics.pass_accuracy is not None else
                     '**Pass accuracy cannot be calculated because the scoring team has no recorded pass attempts.**')
    explanations.append(('How is pass accuracy calculated?',
        f'{accuracy_text}\n\n'
        'The number of completed passes is divided by the number of attempted passes, and the result is multiplied '
        'by 100. Only the scoring team’s passes are counted, and failed attempts are included in the total.\n\n'
        '*This percentage describes the recorded episode. It does not measure a player’s accuracy across a match or season.*'))
    difficulty_text = (f'**The highlighted pass is assigned a difficulty score of {metrics.pass_difficulty:.1f} out of 100.**'
                       if metrics.pass_difficulty is not None else
                       '**A difficulty score cannot be calculated for the highlighted pass.**')
    explanations.append(('What does pass difficulty mean?',
        f'{difficulty_text}\n\n'
        'The highlighted pass receives a higher score for greater distance, more forward progress '
        'and more defender references bypassed.\n\n'
        '- The **distance component** contributes up to 40 points as the pass becomes longer.\n'
        '- The **forward-progress component** contributes up to 30 points as the pass gains ground along X.\n'
        '- The **packing component** contributes up to 30 points. It reaches its maximum at five defenders.\n\n'
        '**The score is calculated with this formula:**\n\n'
        '40 × normalized distance / (100√2) + 30 × positive X gain / 100 + 30 × min(packing / 5, 1), capped at 100.\n\n'
        '*This is not a calibrated completion probability. Missing destination Y means unavailable distance and difficulty.*'))
    explanations.append(('What are the limitations?',
        '**These explanations are based on synthetic events and approximate tactical evidence.**\n\n'
        + '\n'.join(f'- {plain(item)}' for item in evidence.limitations)))
    return explanations


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
