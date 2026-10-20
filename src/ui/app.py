"""Broadcast control room. Launch: uv run streamlit run src/ui/app.py."""
from html import escape
import os

import streamlit as st

from src.ui.service import DEMO_MODES, StudioService, StudioServiceError
from src.ui.visualization import (
    build_event_timeline, build_goal_summary, build_pitch_figure, filter_synchronized_overlays,
)

CSS = """
<style>
:root { color-scheme:dark; --space-8:8px; --space-12:12px; --space-16:16px; --space-24:24px; --studio-font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, "Segoe UI", sans-serif; }
input, button, select, textarea, [data-baseweb="select"], [data-baseweb="popover"] {font-family:var(--studio-font) !important;}
.stApp { background:#090A0F; color:#E8ECF4; font-family:var(--studio-font); }
[data-testid="stHeaderActionElements"] {display:none !important;}
#MainMenu, footer, [data-testid="stAppDeployButton"] {display:none;}
[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"] {display:none !important;}
.block-container {padding-top:1rem !important;}
[data-testid="stMainBlockContainer"] {max-width:1600px;container-type:inline-size;}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {gap:var(--space-16);}
.st-key-studio_header {margin:0 0 8px;gap:16px;align-items:center;}
.studio-bar h1 {padding:0 !important;line-height:1.25 !important;}
.st-key-studio_header [data-testid="stMarkdownContainer"] p {margin:0;}
.st-key-studio_header [data-testid="stPopover"] button {min-height:44px;margin:0;}
.st-key-studio_header > * {min-width:0;}
.st-key-replay_controls {padding:0;margin:0;}
.st-key-replay_controls > * {width:100% !important;min-width:0;}
.st-key-replay_controls [data-testid="stButton"], .st-key-replay_controls button {width:100%;height:100%;box-sizing:border-box;}
.st-key-replay_controls button {min-height:72px;padding:12px;line-height:1.4;}
.simulation-pill {display:inline-block;color:#E8B86D;border:1px solid #886C3F;
 border-radius:999px;padding:4px var(--space-8);font-size:.7rem;white-space:normal;}
.header-title {display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.focus-note {margin-top:8px;padding-top:8px;border-top:1px solid #1E2230;line-height:1.4;}
.st-key-pitch_note {margin:var(--space-8) 0 var(--space-12);}
.st-key-pitch_note p {margin:0;line-height:1.5;}
.studio-bar .badge {white-space:normal;}

[data-testid="stSidebar"] {background:#0D0F15; border-right:1px solid #1E2230;}
[data-testid="stSidebar"] * {color:#E8ECF4;}
[data-testid="stSidebar"] input {color:#E8ECF4;background:#11131A;}
h1,h2,h3 {font-family:var(--studio-font) !important; letter-spacing:-.035em; color:#E8ECF4;}
h1 {font-size:1.6rem !important; font-weight:600 !important; margin:0 !important;}
h2 {font-size:1.12rem !important; font-weight:500 !important;}
p {line-height:1.55; max-width:76ch;}
.studio-bar {min-height:44px;display:flex; justify-content:space-between; align-items:center; gap:.75rem; margin-bottom:0;}
.subtle {color:#A6B0C3;font-size:.84rem;}
.badge {font:11px var(--studio-font); color:#B8C9E6; font-variant-numeric:tabular-nums;white-space:nowrap;}
.dot {display:inline-block;width:6px;height:6px;background:#76ADFF;border-radius:50%;margin-right:8px;}
.dot.warn {background:#E8B86D;}
.bento p {margin:var(--space-12) 0 0;}
.bento h2 {margin:0 0 var(--space-12);padding:0;}
.bento {background:#11131A;border:1px solid #1E2230;border-radius:8px;padding:18px 20px;
 font-variant-numeric:tabular-nums;margin-bottom:var(--space-12);}
.metrics {display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:#1E2230;
 border:1px solid #1E2230;border-radius:8px;overflow:hidden;margin:0 0 8px;}
.metric {min-width:0;overflow:hidden;background:#11131A;padding:var(--space-12) var(--space-16);min-height:0;}
.metric .value {font-size:1rem;font-weight:600;margin-top:3px;line-height:1.25;overflow-wrap:anywhere;}
.caption {font-size:.74rem;color:#A6B0C3;}
.section-line {display:flex;justify-content:space-between;align-items:center;margin:14px 0 8px;}
.overlay {border-left:2px solid #76ADFF;}
.overlay.history {border-left-color:#394256;opacity:.65;}
.overlay.focus {border-left-color:#E8B86D;}
.overlay-row {display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:var(--space-8) var(--space-12);line-height:1.5;}
.metric-overlay {padding:14px 18px;}
.metric-overlay .caption {margin-top:var(--space-8);line-height:1.6;}
.overlay-value {font:18px var(--studio-font);color:#E8ECF4;}
.commentary {font-size:1.15rem;line-height:1.7;}
.narrative-headline {font-size:1.6rem !important;line-height:1.2;}
.engine-facts .badge {white-space:normal;line-height:1.7;}
.engine-facts {background:#151D2A;border-left:3px solid #76ADFF;}
.summary-card {border-left:3px solid #E8B86D;}
.summary-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-12) var(--space-16);margin-top:var(--space-16);}
.pipeline {display:flex;align-items:stretch;gap:var(--space-8);flex-wrap:wrap;margin:0 0 var(--space-12);}
.agent-stage {flex:1;background:#11131A;border:1px solid #394256;border-radius:8px;padding:var(--space-12);font-size:.8rem;line-height:1.5;min-width:0;overflow-wrap:anywhere;}
.agent-stage strong {display:block;margin-bottom:var(--space-8);}
.agent-state {font:11px var(--studio-font);color:#B8C9E6;}
.retry-loop {color:#E8B86D;border:1px solid #E8B86D;border-radius:8px;padding:var(--space-12);margin:0 0 var(--space-12);}
.critic-box {background:#211B14;border:1px solid #886C3F;border-left:3px solid #E8B86D;border-radius:8px;padding:var(--space-16);margin:0 0 var(--space-12);}
.critic-box pre {font-family:var(--studio-font);font-size:.75rem;white-space:pre-wrap;overflow-wrap:anywhere;}
.pipeline-arrow {align-self:center;color:#A6B0C3;}
.st-key-replay_controls button {white-space:normal;text-align:left;}
.st-key-replay_controls button p {white-space:normal !important;overflow:visible !important;text-overflow:clip !important;line-height:1.4;}
.st-key-replay_controls [data-testid="stButton"] {min-width:0;}
@container (max-width:1100px) {
 .studio-bar {flex-wrap:wrap;}
}
@container (max-width:600px) {
 .metrics {grid-template-columns:repeat(2,minmax(0,1fr));}
 .studio-bar {align-items:flex-start;flex-direction:column;gap:8px;}
}
@media(max-width:600px) {
 .st-key-studio_header {flex-wrap:wrap;}
 .studio-bar {flex-wrap:wrap;gap:8px;}
 .metric .value {font-size:.95rem;}
 .pipeline-arrow {display:none;}
 .agent-stage {min-width:0;overflow-wrap:anywhere;}
}

.editorial-badges {display:flex;flex-wrap:wrap;gap:var(--space-8);margin:var(--space-12) 0 var(--space-16);}
.fact-strip {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-16);margin:var(--space-12) 0 0;}
.fact-chip strong {display:block;margin-top:var(--space-8);font-weight:500;line-height:1.5;}
.editorial-pill {border:1px solid #394256;border-radius:999px;padding:4px var(--space-8);font-size:.74rem;color:#B8C9E6;}
.verified-grounds {border-top:1px solid #1E2230;padding-top:var(--space-16);margin-top:var(--space-24);}
.fact-chip {font-size:.78rem;color:#B9C4D6;overflow-wrap:anywhere;}
.sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
.st-key-studio_controls {padding:0 0 8px;background:transparent;}
.st-key-play_navigation {border-top:1px solid #1E2230;padding-top:12px;margin-top:4px;}
.section-heading {margin:var(--space-24) 0 10px !important;padding:0 !important;line-height:1.5;}
/* Native gaps own telemetry spacing; nested cards do not add a second margin. */
.st-key-telemetry {gap:0 !important;}
.st-key-telemetry [data-testid="stMarkdownContainer"] {display:flow-root;}
.telemetry-stack {display:flex !important;flex-direction:column !important;gap:14px !important;margin-bottom:14px !important;}
.telemetry-stack > * {margin:0 !important;}
.st-key-telemetry .bento, .st-key-telemetry .pipeline,
.st-key-telemetry .retry-loop, .st-key-telemetry .critic-box {margin:0;}
.st-key-telemetry button {min-height:44px;padding:var(--space-8) var(--space-16);}
.st-key-telemetry_domain {margin-top:14px;margin-bottom:12px;}
.bento, .bento *, .metrics, .metric, .pipeline, .agent-stage, .retry-loop, .critic-box,
.studio-bar, .editorial-badges, .editorial-pill, .verified-grounds, .fact-strip, .fact-chip,
.summary-grid, .overlay-row, .trace {box-sizing:border-box;}
.bento, .fact-chip, .summary-grid > *, .editorial-badges > * {min-width:0;overflow-wrap:anywhere;}
@media(max-width:400px) {
 .fact-strip, .summary-grid {grid-template-columns:minmax(0,1fr);}
 .pipeline {flex-direction:column;}
 .pipeline-arrow {display:none;}
}
.breakdown {color:#B9C4D6;font-size:.88rem;line-height:1.65;}
.trace {border-left:1px solid #394256;padding-left:12px;margin:12px 0;font-size:.8rem;}
button:focus-visible, input:focus-visible, [role="combobox"]:focus-visible {outline:2px solid #76ADFF !important;outline-offset:3px;}
[data-testid="stPlotlyChart"] {border:1px solid #1E2230;border-radius:8px;overflow:hidden;}
[data-baseweb="select"] > div {background:#11131A;color:#E8ECF4;border-color:#394256;}
@media(max-width:900px) {.metrics{grid-template-columns:repeat(3,minmax(0,1fr));}}
@media(max-width:500px) {.metrics{grid-template-columns:repeat(2,minmax(0,1fr));}.studio-bar{align-items:flex-start;flex-direction:column;}}
@media(prefers-reduced-motion:reduce) {*{animation:none !important;transition:none !important;}}
</style>
"""


def html_card(content: str, classes: str = '') -> None:
    st.markdown(f'<div class="bento {classes}">{content}</div>', unsafe_allow_html=True)


EPISODE_LABELS = {
    'SYNTH_GOAL_01': 'Quick counterattack / 8.2 seconds',
    'SYNTH_GOAL_02': 'Breaking the defensive line / 20 seconds',
    'SYNTH_GOAL_03': 'Patient buildup / 28 seconds',
}
PERSONA_LABELS = {
    'TACTICAL_ANALYST': 'Tactical analyst',
    'PASSIONATE_FAN': 'Passionate fan',
    'CASUAL_VIEWER': 'Casual viewer',
}


def seek_replay(offset: float) -> None:
    """Widget callback updates the clock before Streamlit redraws it."""
    st.session_state['replay_clock'] = offset


def regenerate_narrative() -> None:
    """Invalidate the cached narrative before the next script run."""
    st.session_state.pop('_result_key', None)


def render_overlay(item) -> None:
    overlay = item.overlay
    html_card(
        f'<div class="overlay-row"><span>{escape(overlay.label)}</span>'
        f'<span class="overlay-value">{overlay.value:.1f} <small>{escape(overlay.unit)}</small></span></div>'
        f'<div class="caption">{escape(overlay.player_name)} / +{item.relative_sec:.1f}s / '
        f'{"On screen now" if item.is_active else "Earlier in this replay"}</div>',
        'metric-overlay overlay' + (' history' if not item.is_active else '') + (' focus' if overlay.is_focus else ''),
    )


def render_pipeline(telemetry, summary_html: str) -> None:
    """Show completed execution evidence, not a simulated live processing animation."""
    recovered = telemetry.status == 'RECOVERED'
    fallback = telemetry.status == 'DEGRADED_FALLBACK'
    labels = [
        ('1. Tactical Analyst', 'Facts ready'),
        ('2. Persona Narrator', 'Drafts rejected' if fallback else 'Repaired' if recovered else 'Draft accepted'),
        ('3. Guardrail Critic', 'Fallback validated' if fallback else 'Accepted'),
    ]
    stages = '<span class="pipeline-arrow" aria-hidden="true">→</span>'.join(
        f'<div class="agent-stage"><strong>{label}</strong><span class="agent-state">{state}</span></div>'
        for label, state in labels
    )
    blocks = [f'<div class="pipeline" aria-label="Completed agent execution">{stages}</div>', summary_html]
    has_return = any(h.from_agent == 'GuardrailCriticAgent' and h.to_agent == 'PersonaNarratorAgent'
                     for h in telemetry.handoffs)
    if has_return:
        blocks.append('<div class="retry-loop">↩ Critic → Narrator / repair requested / '
                      'second generation attempt completed</div>')
    if telemetry.critic_feedback:
        for number, feedback in enumerate(telemetry.critic_feedback, 1):
            blocks.append(f'<div class="critic-box" role="status"><strong>Draft {number} rejected by the critic</strong>'
                        '<p>The draft failed a grounding or output rule. '
                        'The reason below was recorded before requesting a repair or producing the safe fallback.</p>'
                        f'<pre>{escape(feedback)}</pre></div>')
    st.markdown('<div class="telemetry-stack" style="display:flex;flex-direction:column;gap:14px;margin-bottom:14px;">'
                + ''.join(blocks) + '</div>', unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title='Touchline / Broadcast Studio', layout='wide', initial_sidebar_state='collapsed')
    st.markdown(CSS, unsafe_allow_html=True)
    service = StudioService(os.getenv('API_BASE_URL') or None)
    source = 'Remote API' if service.api_base_url else 'Local / offline'
    with st.container(key='studio_header'):
        title_column, help_column = st.columns([6, 1], vertical_alignment='center')
        title_column.markdown('<div class="studio-bar"><h1>Broadcast studio</h1></div>', unsafe_allow_html=True)
        with help_column.container(horizontal_alignment='right'):
            with st.popover('Help'):
                st.markdown('Choose a **Play** above the episode metrics. Personalize the story in the right column. Select a **Key Events** milestone on the left '
                            'to inspect that moment; the final milestone shows the full play. '
                            'Episode metrics stay fixed while the pitch and overlays follow your selection. '
                            'Use **Agent behavior** beside the telemetry diagram to demonstrate a clean run, critic recovery or safe fallback.')
                st.caption(source + ' / Fictional players and events. Normalized coordinates; static defensive snapshot.')
    with st.container(key='studio_controls'):
        try:
            ids = service.list_goal_ids()
        except StudioServiceError as error:
            html_card(escape(str(error)))
            return
        if not ids:
            html_card('No episodes loaded. Load synthetic episodes in the backend and refresh.')
            return
        goal_id = st.selectbox('Play', ids, key='episode', format_func=lambda value: EPISODE_LABELS.get(value, value))
        episode_key = (service.api_base_url, goal_id)
        try:
            if st.session_state.get('_episode_key') != episode_key:
                st.session_state['_episode_data'] = service.get_episode(goal_id)
                st.session_state['_episode_key'] = episode_key
                st.session_state.pop('focus', None)
                st.session_state.pop('_result_key', None)
                st.session_state.pop('replay_clock', None)
            episode = st.session_state['_episode_data']
        except StudioServiceError as error:
            html_card(escape(str(error)))
            return
    metrics_slot = st.empty()
    left, right = st.columns([1.65, 1], gap='medium')
    with left:
        tactical_slot = st.container(key='tactical_domain')
    with right:
        st.markdown('<h2 class="section-heading">Why this goal happened</h2>', unsafe_allow_html=True)
        narrative_controls = st.columns(3, vertical_alignment='bottom', gap='small')
        persona = narrative_controls[0].selectbox('Commentary style', list(PERSONA_LABELS), key='persona', format_func=PERSONA_LABELS.get)
        language = narrative_controls[1].selectbox('Language', ['en', 'es'], key='language', format_func=lambda value: 'English' if value == 'en' else 'Español')
        players = {event.player_id: event.player_name for event in episode.events}
        focus_id = narrative_controls[2].selectbox('Focus player', [None, *players, 'P_99'], key='focus',
                                format_func=lambda player: 'Whole team' if player is None else players.get(player, 'External player / absent'))
        editorial_slot = st.container(key='editorial_domain')
        st.markdown('<h2 class="section-heading">Multi-agent telemetry</h2>', unsafe_allow_html=True)
        agent_controls = st.columns([1.4, 1], vertical_alignment='bottom', gap='small')
        behavior_labels = dict(zip(DEMO_MODES, [
            'Clean run (first-pass success)',
            'Single mistake (critic recovers)',
            'Repeated mistake (safe fallback)',
        ]))
        mode = agent_controls[0].selectbox('Agent behavior', DEMO_MODES, key='demo_mode',
                                     format_func=behavior_labels.get)
        agent_controls[1].button('Regenerate narrative', key='regenerate_narrative', on_click=regenerate_narrative,
                                 width='stretch', wrap=True)
        telemetry_slot = st.container(key='telemetry_domain')
    key = (episode_key, persona, language, focus_id, mode)
    try:
        if st.session_state.get('_result_key') != key:
            st.session_state['_broadcast'] = service.broadcast(
                episode, persona=persona, language=language, focus_player_id=focus_id, mode=mode,
            )
            st.session_state['_result_key'] = key
        result = st.session_state['_broadcast']
    except StudioServiceError as error:
        html_card(escape(str(error)))
        return
    telemetry = result.telemetry
    status = telemetry.status
    simulated = mode != 'Normal'
    analysis, metrics = result.analysis, result.broadcast_metrics
    pivot = next((event.player_name for event in episode.events if event.player_id == analysis.tactical_pivot), 'Unavailable')
    values = [
        ('Defenders bypassed', str(analysis.sequence_packing_score)), ('Key connector', pivot),
        ('Breakthrough zone', analysis.breakdown_zone or 'Unavailable'),
        ('Play rhythm', 'Fast transition' if metrics.tempo_classification == 'HIGH_TEMPO_CHAOS' else 'Controlled buildup' if metrics.tempo_classification else 'Unavailable'),
        ('Pass difficulty', f'{metrics.pass_difficulty:.1f} / 100' if metrics.pass_difficulty is not None else 'Unavailable'),
        ('Pass accuracy', f'{100*metrics.pass_accuracy:.0f}%' if metrics.pass_accuracy is not None else 'Unavailable'),
    ]
    metrics_slot.markdown('<div class="metrics">' + ''.join(
        f'<div class="metric"><div class="caption">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in values) + '</div>', unsafe_allow_html=True)
    duration = episode.timestamp_goal - min(event.timestamp_sec for event in episode.events)
    st.session_state.setdefault('replay_clock', float(duration))
    current = float(st.session_state['replay_clock'])
    timeline = build_event_timeline(result, current)
    clock = current
    frame = filter_synchronized_overlays(result, clock)
    with tactical_slot:
        with st.container(key='play_navigation', gap='small'):
            st.markdown('<h2 class="section-heading">Key Events</h2>', unsafe_allow_html=True)
            with st.container(key='replay_controls'):
                columns = st.columns(len(timeline), gap='small')
                for number, (column, milestone) in enumerate(zip(columns, timeline), 1):
                    label = milestone.label
                    if number == len(timeline):
                        label += ' / Full play'
                    with column:
                        st.button(f'{number}. +{milestone.relative_sec:.1f}s · {label}  \n'
                                  f'{milestone.player_name}{" · Current" if milestone.is_current else ""}',
                                  key=f'milestone_{milestone.event_id}',
                                  type='primary' if milestone.is_current else 'secondary',
                                  on_click=seek_replay, args=(milestone.relative_sec,), width='stretch', wrap=True)
        st.markdown('<h2 class="section-heading">Explore the play</h2>', unsafe_allow_html=True)
        figure = build_pitch_figure(result, clock)
        figure.update_layout(height=420)
        st.plotly_chart(figure, width='stretch',
                        config={'displayModeBar': False}, theme=None, key='pitch')
        with st.container(key='pitch_note'):
            st.caption('Defenders are a static snapshot; active/bypassed refers only to the key-pass comparison.')
        st.markdown('<h2 class="section-heading">On-screen facts at this moment</h2>', unsafe_allow_html=True)
        active_overlays = [item for item in frame.timed_overlays if item.is_active]
        history = [item for item in frame.timed_overlays if not item.is_active]
        summary = build_goal_summary(result, clock)
        if summary is not None:
            accuracy = f'{100 * summary.pass_accuracy:.0f}%' if summary.pass_accuracy is not None else 'Unavailable'
            html_card('<h2>Goal Sequence Summary</h2><div class="caption">Consolidated episode facts / goal reached</div>'
                      '<div class="summary-grid">'
                      f'<div><span class="caption">Sequence duration</span><br><strong>{summary.duration_sec:.1f}s</strong></div>'
                      f'<div><span class="caption">Accumulated pass accuracy</span><br><strong>{accuracy}</strong></div>'
                      f'<div><span class="caption">Maximum packing</span><br><strong>{summary.maximum_packing}</strong></div>'
                      f'<div><span class="caption">Final shooter</span><br><strong>{escape(summary.final_shooter or "Unavailable")}</strong></div>'
                      '</div>', 'summary-card')
        if not active_overlays and summary is None:
            html_card('No metric is triggered at this event. Select the Key pass milestone to see the pass overlays.', 'overlay history')
        for item in active_overlays:
            render_overlay(item)
        if history:
            with st.expander(f'Earlier overlays ({len(history)})', expanded=False):
                for item in reversed(history):
                    render_overlay(item)
    with editorial_slot:
        focus = result.focus
        focus_text = ('Whole team' if focus.player_id is None else
                      f'{focus.player_name} · {len(focus.event_ids)} actions' if focus.participated else
                      'External player · absent')
        grounds = [('Packing', str(analysis.sequence_packing_score)), ('Tactical pivot', pivot),
                   ('Breakdown zone', analysis.breakdown_zone or 'Unavailable'), ('Tactical cause', analysis.tactical_cause)]
        chips = ''.join(f'<div class="fact-chip"><span class="caption">{label}</span><strong>{escape(value)}</strong></div>'
                        for label, value in grounds)
        html_card(f'<h2 class="narrative-headline">{escape(result.narrative.headline)}</h2>'
                  '<div class="editorial-badges">'
                  f'<span class="editorial-pill">{escape(PERSONA_LABELS[persona])} · {language.upper()}</span>'
                  f'<span class="editorial-pill">Focus: {escape(focus_text)}</span></div>'
                  f'<p class="commentary">{escape(result.narrative.commentary)}</p>'
                  '<div class="verified-grounds"><div class="caption">Verified tactical grounds</div>'
                  f'<div class="fact-strip">{chips}</div>'
                  f'<span class="sr-only">{escape(result.narrative.tactical_breakdown)}</span></div>', 'editorial-card')
    with telemetry_slot:
        outcome = {'SUCCESS': 'Accepted', 'RECOVERED': 'Recovered after retry',
                   'DEGRADED_FALLBACK': 'Safe fallback'}[status]
        with st.container(key='telemetry'):
            render_pipeline(telemetry, f'<div class="bento"><strong>{outcome}</strong>'
                      f'<p>{telemetry.attempts} generation attempts / {len(telemetry.handoffs)} handoffs</p>'
                      f'<div class="caption">Orchestration latency: {telemetry.latency_ms:.2f} ms / '
                      f'{"Local simulation" if simulated else escape(source)}</div></div>')
            with st.expander('Inspect agent handoffs', expanded=simulated):
                for handoff in telemetry.handoffs:
                    html_card(f'<div class="caption">Attempt {handoff.attempt}</div>'
                              f'<div>{escape(handoff.from_agent)} → {escape(handoff.to_agent)}</div>'
                              f'<p class="caption">{escape(handoff.reason)}</p>')


if __name__ == '__main__':
    main()
