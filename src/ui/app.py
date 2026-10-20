"""Broadcast control room. Launch: uv run streamlit run src/ui/app.py."""
from html import escape
import os

import streamlit as st

from src.ui.service import DEMO_MODES, StudioService, StudioServiceError
from src.ui.visualization import build_pitch_figure, filter_synchronized_overlays

CSS = """
<style>
:root { color-scheme:dark; }
.stApp { background:#090A0F; color:#E8ECF4; font-family:Arial,sans-serif; }
#MainMenu, footer, [data-testid="stToolbar"] {display:none;}
[data-testid="stHeader"] {background:transparent;height:0;}
[data-testid="stSidebarCollapsedControl"] {visibility:visible;background:#11131A;}
[data-testid="stMainBlockContainer"] {padding-top:1.8rem; max-width:1600px;}
[data-testid="stSidebar"] {background:#0D0F15; border-right:1px solid #1E2230;}
[data-testid="stSidebar"] * {color:#E8ECF4;}
[data-testid="stSidebar"] input {color:#E8ECF4;background:#11131A;}
h1,h2,h3 {font-family:Arial,sans-serif !important; letter-spacing:-.035em; color:#E8ECF4;}
h1 {font-size:2rem !important; font-weight:600 !important; margin:0 !important;}
h2 {font-size:1.12rem !important; font-weight:500 !important;}
p {line-height:1.55; max-width:76ch;}
.studio-bar {display:flex; justify-content:space-between; align-items:center; gap:1rem; margin-bottom:1.4rem;}
.subtle {color:#A6B0C3;font-size:.84rem;}
.badge {font:11px ui-monospace,Menlo,monospace; color:#B8C9E6; white-space:nowrap;}
.dot {display:inline-block;width:6px;height:6px;background:#76ADFF;border-radius:50%;margin-right:8px;}
.dot.warn {background:#E8B86D;}
.bento {background:#11131A;border:1px solid #1E2230;border-radius:8px;padding:18px;
 font-variant-numeric:tabular-nums;margin-bottom:12px;}
.metrics {display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:#1E2230;
 border:1px solid #1E2230;border-radius:8px;overflow:hidden;margin:0 0 20px;}
.metric {background:#11131A;padding:16px 13px;min-height:90px;}
.metric .value {font-size:1.12rem;font-weight:600;margin-top:9px;overflow-wrap:anywhere;}
.caption {font-size:.74rem;color:#A6B0C3;}
.section-line {display:flex;justify-content:space-between;align-items:center;margin:14px 0 8px;}
.overlay {border-left:2px solid #76ADFF;}
.overlay.history {border-left-color:#394256;opacity:.65;}
.overlay.focus {border-left-color:#E8B86D;}
.overlay-row {display:flex;justify-content:space-between;gap:12px;}
.overlay-value {font:18px ui-monospace,Menlo,monospace;color:#E8ECF4;}
.commentary {font-size:1.05rem;line-height:1.65;}
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


def render_overlay(item) -> None:
    overlay = item.overlay
    classes = 'overlay' + (' focus' if overlay.is_focus else '') + ('' if item.is_active else ' history')
    html_card(
        f'<div class="overlay-row"><span>{escape(overlay.label)}</span>'
        f'<span class="overlay-value">{overlay.value:.1f} <small>{escape(overlay.unit)}</small></span></div>'
        f'<div class="caption">{escape(overlay.player_name)} / +{item.relative_sec:.1f}s / '
        f'{"On screen now" if item.is_active else "Earlier in this replay"}</div>', classes,
    )


def main() -> None:
    st.set_page_config(page_title='Touchline / Broadcast Studio', layout='wide', initial_sidebar_state='expanded')
    st.markdown(CSS, unsafe_allow_html=True)
    service = StudioService(os.getenv('API_BASE_URL') or None)
    source = 'Remote API' if service.api_base_url else 'Local / offline'
    with st.sidebar:
        st.markdown('## Touchline')
        st.caption('Broadcast studio / synthetic replay')
        try:
            ids = service.list_goal_ids()
        except StudioServiceError as error:
            html_card(escape(str(error)))
            return
        if not ids:
            html_card('No episodes loaded. Load synthetic episodes in the backend and refresh.')
            return
        goal_id = st.selectbox('Choose a play', ids, key='episode', format_func=lambda value: EPISODE_LABELS.get(value, value))
        persona = st.selectbox('Commentary style', list(PERSONA_LABELS), key='persona', format_func=PERSONA_LABELS.get, help='Changes the voice of the commentary; tactical facts stay the same.')
        language = st.selectbox('Commentary language', ['en', 'es'], key='language', format_func=lambda value: 'English' if value == 'en' else 'Español')
        episode_key = (service.api_base_url, goal_id)
        try:
            if st.session_state.get('_episode_key') != episode_key:
                st.session_state['_episode_data'] = service.get_episode(goal_id)
                st.session_state['_episode_key'] = episode_key
                st.session_state.pop('focus', None)
                st.session_state.pop('_result_key', None)
            episode = st.session_state['_episode_data']
        except StudioServiceError as error:
            html_card(escape(str(error)))
            return
        players = {event.player_id: event.player_name for event in episode.events}
        focus_id = st.selectbox('Focus player', [None, *players, 'P_99'], key='focus',
                                format_func=lambda player: 'Whole team' if player is None else players.get(player, 'External player / absent'), help='Highlight a player on the pitch and mention their recorded involvement.')
        with st.expander('Recovery demo / advanced'):
            st.caption('Deliberately reject a draft to watch the critic request a repair or produce a safe fallback.')
            mode = st.selectbox('Agent demo mode', DEMO_MODES, key='demo_mode')
        st.caption(source)
        st.caption('Normalized pitch coordinates. Static defensive snapshot. Fictional players and events.')
        regenerate = st.button('Regenerate narrative', width='stretch')
    key = (episode_key, persona, language, focus_id, mode)
    try:
        if regenerate or st.session_state.get('_result_key') != key:
            st.session_state['_broadcast'] = service.broadcast(
                episode, persona=persona, language=language, focus_player_id=focus_id, mode=mode,
            )
            st.session_state['_result_key'] = key
            st.session_state.pop('replay_clock', None)
        result = st.session_state['_broadcast']
    except StudioServiceError as error:
        html_card(escape(str(error)))
        return
    telemetry = result.telemetry
    status = telemetry.status
    simulated = mode != 'Normal'
    st.markdown(
        '<div class="studio-bar"><div><h1>Broadcast studio</h1>'
        '<div class="subtle">A goal sequence, with the evidence in view.</div></div>'
        f'<div class="badge"><span class="dot"></span>[LIVE REPLAY] &nbsp; '
        f'<span class="dot {"warn" if status != "SUCCESS" else ""}"></span>[CRITIC: {escape(status)}]</div></div>',
        unsafe_allow_html=True,
    )
    html_card('<strong>New here?</strong> The full play is shown first. '
              'Choose a play in the left panel, then select <strong>View key pass</strong> '
              'to see the main breakthrough. Use <strong>Start replay</strong> and '
              '<strong>Next event</strong> to inspect it step by step.')
    if simulated:
        html_card('Local failure simulation / ' + escape(mode), 'overlay focus')
    analysis, metrics = result.analysis, result.broadcast_metrics
    pivot = next((event.player_name for event in episode.events if event.player_id == analysis.tactical_pivot), 'Unavailable')
    values = [
        ('Defenders bypassed', str(analysis.sequence_packing_score)), ('Key connector', pivot),
        ('Breakthrough zone', analysis.breakdown_zone or 'Unavailable'),
        ('Play rhythm', 'Fast transition' if metrics.tempo_classification == 'HIGH_TEMPO_CHAOS' else 'Controlled buildup' if metrics.tempo_classification else 'Unavailable'),
        ('Pass difficulty', f'{metrics.pass_difficulty:.1f} / 100' if metrics.pass_difficulty is not None else 'Unavailable'),
        ('Pass accuracy', f'{100*metrics.pass_accuracy:.0f}%' if metrics.pass_accuracy is not None else 'Unavailable'),
    ]
    st.markdown('<div class="metrics">' + ''.join(
        f'<div class="metric"><div class="caption">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in values) + '</div>', unsafe_allow_html=True)
    st.caption('Full-episode analysis / the replay clock controls event and overlay visibility.')
    duration = episode.timestamp_goal - min(event.timestamp_sec for event in episode.events)
    st.session_state.setdefault('replay_clock', float(duration))
    current = float(st.session_state['replay_clock'])
    first_time = min(event.timestamp_sec for event in episode.events)
    event_offsets = sorted({event.timestamp_sec - first_time for event in episode.events})
    next_offset = next((offset for offset in event_offsets if offset > current + 1e-9), duration)
    key_event = next((event for event in episode.events if event.event_id == metrics.key_pass_event_id), None)
    restart, advance, key_control, full = st.columns(4)
    restart.button('Start replay', key='restart_replay', on_click=seek_replay, args=(0.0,), width='stretch')
    advance.button('Next event', key='next_event', on_click=seek_replay,
                   args=(next_offset,), disabled=current >= duration, width='stretch')
    key_control.button('View key pass', key='key_pass', type='primary', on_click=seek_replay,
                       args=(key_event.timestamp_sec-first_time if key_event else 0.0,),
                       disabled=key_event is None, width='stretch')
    full.button('Show full play', key='full_play', on_click=seek_replay, args=(float(duration),), width='stretch')
    if duration > 0:
        clock = st.slider('Replay clock (seconds)', 0.0, float(duration), step=0.1,
                          format='%.1fs', key='replay_clock')
    else:
        clock = 0.0
        st.caption('Single instant / 0.0s')
    frame = filter_synchronized_overlays(result, clock)
    left, right = st.columns([1.65, 1], gap='large')
    with left:
        st.markdown('## Explore the play')
        active = [item.event for item in frame.events if item.is_active]
        event_text = '; '.join(f'{event.player_name}: {event.event_type.lower()}' for event in active)
        html_card(f'<div class="caption">Selected moment / +{clock:.1f}s of {duration:.1f}s</div>'
                  f'<strong>{escape(event_text)}</strong>')
        st.plotly_chart(build_pitch_figure(result, clock), width='stretch',
                        config={'displayModeBar': False}, theme=None, key='pitch')
        st.caption('Amber: key pass. Blue ring: focused player. Rose crosses: defenders bypassed in the static snapshot.')
        st.markdown('## On-screen facts at this moment')
        active_overlays = [item for item in frame.timed_overlays if item.is_active]
        history = [item for item in frame.timed_overlays if not item.is_active]
        if not active_overlays:
            html_card('No metric is triggered at this event. Select View key pass to see the pass overlays.', 'overlay history')
        for item in active_overlays:
            render_overlay(item)
        if history:
            with st.expander(f'Earlier overlays ({len(history)})'):
                for item in reversed(history):
                    render_overlay(item)
    with right:
        st.markdown('## Why this goal happened')
        html_card(f'<h2>{escape(result.narrative.headline)}</h2>'
                  f'<p class="commentary">{escape(result.narrative.commentary)}</p>'
                  f'<p class="breakdown">{escape(result.narrative.tactical_breakdown)}</p>')
        focus = result.focus
        focus_text = ('No player focus selected.' if focus.player_id is None else
                      f'{focus.player_name} / {len(focus.event_ids)} recorded interventions.' if focus.participated else
                      'Selected player is absent from this sequence. No involvement is attributed.')
        html_card('<div class="caption">Player focus</div><p>' + escape(focus_text) + '</p>')
        st.markdown('## Multi-agent telemetry')
        html_card(f'<div class="badge">[CRITIC: {escape(status)}]</div>'
                  f'<p>{telemetry.attempts} generation attempts / {len(telemetry.handoffs)} handoffs</p>'
                  f'<div class="caption">Orchestration latency: {telemetry.latency_ms:.2f} ms / '
                  f'{"Local simulation" if simulated else escape(source)}</div>')
        with st.expander('Inspect agent handoffs', expanded=simulated):
            for handoff in telemetry.handoffs:
                html_card(f'<div class="caption">Attempt {handoff.attempt}</div>'
                          f'<div>{escape(handoff.from_agent)} → {escape(handoff.to_agent)}</div>'
                          f'<p class="caption">{escape(handoff.reason)}</p>')
        if telemetry.critic_feedback:
            with st.expander('Critic feedback', expanded=simulated):
                for feedback in telemetry.critic_feedback:
                    st.text(feedback)


if __name__ == '__main__':
    main()
