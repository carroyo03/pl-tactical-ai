"""Broadcast control room. Launch: uv run streamlit run src/ui/app.py."""
from html import escape
from hashlib import sha256
from pathlib import Path
import os

import streamlit as st

from src.agents import narrator as narrator_module
from src.ui.service import DEMO_MODES, StudioService, StudioServiceError
from src.ui.demos import DEMO_ERRORS, DemoReview, available_demo_errors, explain_critic_feedback
from src.ui.visualization import (
    build_analysis_explanations, build_event_timeline, build_goal_summary, build_pitch_figure, filter_synchronized_overlays,
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
.st-key-replay_controls button {height:104px !important;min-height:104px;padding:16px;line-height:1.4;}
.st-key-replay_controls [data-testid="stHorizontalBlock"] {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:stretch;}
.st-key-replay_controls [data-testid="stColumn"] {width:100% !important;min-width:0;}
.st-key-replay_controls button[kind="primary"] {border:2px solid #B9D4FF;}
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
.bento {background:#11131A;border:1px solid #1E2230;border-radius:8px;padding:24px;
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
.st-key-play_navigation {padding:0;margin:0 0 24px;}
.section-heading {margin:var(--space-24) 0 10px !important;padding:0 !important;line-height:1.5;}
/* Native gaps own telemetry spacing; nested cards do not add a second margin. */

.st-key-telemetry [data-testid="stMarkdownContainer"] {display:flow-root;}
.telemetry-stack {display:flex !important;flex-direction:column !important;gap:14px !important;margin-bottom:14px !important;}
.telemetry-stack > * {margin:0 !important;}
.st-key-telemetry .bento, .st-key-telemetry .pipeline,
.st-key-telemetry .retry-loop, .st-key-telemetry .critic-box {margin:0;}
.st-key-telemetry button {min-height:44px;padding:var(--space-8) var(--space-16);}
.st-key-editorial_domain {padding-top:16px;}
.st-key-telemetry_domain {padding-top:4px;padding-bottom:0;}
/* Keep disclosures adjacent when stacked; align their top edges only in two-column mode. */
@media(min-width:1181px) {
 .st-key-studio_domains [data-testid="stHorizontalBlock"]:has(.st-key-tactical_domain) {align-items:stretch;}
 .st-key-studio_domains [data-testid="stColumn"]:is(:has(.st-key-tactical_domain), :has(.st-key-editorial_domain)) {
  display:flex;flex-direction:column;align-self:stretch;
 }
 /* Streamlit places a layout wrapper between each column and its vertical block. */
 .st-key-studio_domains [data-testid="stColumn"]:is(:has(.st-key-tactical_domain), :has(.st-key-editorial_domain)) > div {
  display:flex;flex-direction:column;flex:1 1 auto;
 }
 .st-key-studio_domains [data-testid="stColumn"]:is(:has(.st-key-tactical_domain), :has(.st-key-editorial_domain)) > div > [data-testid="stVerticalBlock"] {
  flex:1 1 auto;
 }
 .st-key-overlay_history, .st-key-technical_details {margin-top:auto;}
}

.verified-grounds {padding-bottom:8px;}
.agent-stage {padding:16px;}
@container (max-width:1100px) {
 .st-key-replay_controls [data-testid="stHorizontalBlock"] {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media(max-width:600px) {
 .bento {padding:20px;}
 .st-key-replay_controls button {padding:12px;}
}
.handoff-list {display:flex !important;flex-direction:column;gap:16px !important;padding:16px;box-sizing:border-box;}
.handoff-list .handoff-card {margin:0 !important;padding:20px;}
.handoff-route {margin-top:8px;line-height:1.5;overflow-wrap:anywhere;}
.bento, .bento *, .metrics, .metric, .pipeline, .agent-stage, .retry-loop, .critic-box,
.studio-bar, .editorial-badges, .editorial-pill, .verified-grounds, .fact-strip, .fact-chip,
.summary-grid, .overlay-row, .trace {box-sizing:border-box;}
.bento, .fact-chip, .summary-grid > *, .editorial-badges > * {min-width:0;overflow-wrap:anywhere;}
@media(max-width:320px) {
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
.pitch-legend {display:flex;flex-wrap:wrap;gap:10px 18px;margin-bottom:12px;line-height:1.5;font-size:.78rem;}
.pitch-legend span {white-space:nowrap;}
.st-key-pitch_surface {padding:16px;background:#11131A;border:1px solid #1E2230;border-radius:8px;}
.st-key-pitch_surface [data-testid="stPlotlyChart"] {border:0;border-radius:0;}
@media(max-width:600px) {
 .block-container {padding-left:16px !important;padding-right:16px !important;}
 .st-key-studio_header [data-testid="stHorizontalBlock"] {display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;}
 .st-key-studio_header [data-testid="stColumn"] {width:100% !important;min-width:0;}
 .studio-bar h1 {font-size:1.35rem !important;}
 .section-heading {margin-top:16px !important;margin-bottom:8px !important;}
 .st-key-play_navigation {margin-bottom:12px;}
 .st-key-narrative_controls [data-testid="stHorizontalBlock"] {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
 .st-key-narrative_controls [data-testid="stColumn"] {width:100% !important;min-width:0;}
 .st-key-narrative_controls [data-testid="stColumn"]:first-child {grid-column:1 / -1;}
 .pipeline {flex-direction:column;}
 .commentary {font-size:1rem;line-height:1.65;}
 .narrative-headline {font-size:1.35rem !important;}
 .handoff-list {padding:8px;gap:12px !important;}
 .handoff-list .handoff-card {padding:16px;}
 .pitch-legend {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;font-size:.7rem;}
 .pitch-legend span {white-space:normal;}
 .st-key-pitch_surface {padding:12px;}
}
/* Tablet layout follows usable width rather than a device model. */
@media(max-width:1180px) {
 .block-container {padding-left:24px !important;padding-right:24px !important;}
 .st-key-studio_domains [data-testid="stHorizontalBlock"]:has(.st-key-tactical_domain) {flex-direction:column;gap:32px;align-items:stretch;}
 .st-key-studio_domains [data-testid="stColumn"]:has(.st-key-tactical_domain),
 .st-key-studio_domains [data-testid="stColumn"]:has(.st-key-editorial_domain) {width:100% !important;flex:1 1 auto !important;min-width:0;}
}
@media(min-width:601px) and (max-width:1180px) {
 .metrics {grid-template-columns:repeat(3,minmax(0,1fr));}
 .st-key-replay_controls [data-testid="stHorizontalBlock"] {grid-template-columns:repeat(4,minmax(0,1fr));}
 .pitch-legend {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 24px;}
 .section-heading {margin-top:20px !important;}
}
.st-key-narrative_controls, .st-key-agent_controls, .st-key-telemetry_domain {container-type:inline-size;}
@container (max-width:480px) {
 .st-key-narrative_controls [data-testid="stHorizontalBlock"] {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
 .st-key-narrative_controls [data-testid="stColumn"] {width:100% !important;min-width:0;}
 .st-key-narrative_controls [data-testid="stColumn"]:first-child {grid-column:1 / -1;}
 .pipeline {flex-direction:column;}
 .pipeline-arrow {display:none;}
 .agent-stage {overflow-wrap:normal;word-break:normal;}
}
@media(max-width:600px) {
 .block-container {padding-left:16px !important;padding-right:16px !important;}
}
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


PROVIDER_LABELS = {
    'GROQ': 'Groq', 'OFFLINE_MOCK': 'Offline mock', 'AZURE_OPENAI': 'Azure OpenAI',
    'OFFLINE_FALLBACK': 'Offline fallback', 'CUSTOM': 'Custom client', 'UNKNOWN': 'Provider not reported',
}


def seek_replay(offset: float) -> None:
    """Widget callback updates the clock before Streamlit redraws it."""
    st.session_state['replay_clock'] = offset


def render_overlay(item) -> None:
    overlay = item.overlay
    html_card(
        f'<div class="overlay-row"><span>{escape(overlay.label)}</span>'
        f'<span class="overlay-value">{overlay.value:.1f} <small>{escape(overlay.unit)}</small></span></div>'
        f'<div class="caption">{escape(overlay.player_name)} / +{item.relative_sec:.1f}s / '
        f'{"On screen now" if item.is_active else "Earlier in this replay"}</div>',
        'metric-overlay overlay' + (' history' if not item.is_active else '') + (' focus' if overlay.is_focus else ''),
    )


def render_critic_review(telemetry, review: DemoReview | None) -> None:
    """Explain recorded rejections inline within the guided review."""
    if not telemetry.critic_feedback:
        return
    if review is not None:
        st.caption('These drafts were deliberately made incorrect for this local demonstration. They were not published as commentary.')
        for index, draft in enumerate(review.rejected_drafts, 1):
            with st.container(border=True):
                st.markdown(f'**Draft {index} was rejected**')
                st.markdown('**What was written**')
                st.text(draft.headline)
                st.text(draft.commentary)
                st.markdown('**Why a correction was needed**')
                st.text(explain_critic_feedback(draft.feedback))
        st.divider()
        st.markdown('**What the recorded events support**')
        st.text(review.evidence_explanation)
    else:
        availability = {
            'provider_cooldown': 'The model allowance or local capacity was temporarily unavailable. No further model request was made.',
            'provider_quota': 'The provider reported a temporary usage limit. A prepared explanation was selected instead of waiting.',
            'provider_configuration': 'The model connection needs an operator configuration check. Repeating the same request would not resolve it.',
            'provider_timeout': 'The model did not respond within the available time.',
            'provider_connection': 'The model service could not be reached.',
            'provider_unavailable': 'The model service was temporarily unavailable.',
            'generation_deadline': 'The available generation time or capacity was exhausted before another model request could begin.',
            'generation_cancelled': 'The request was interrupted. No further generation was started.',
            'provider_invalid_output': 'The response did not meet the required format or evidence limitations.',
            'provider_incomplete': 'The model did not return a complete, usable explanation.',
            'provider_empty': 'The model returned no explanation.',
            'input_limit': 'The supplied evidence exceeded the configured model input limit.',
        }
        for number, feedback in enumerate(telemetry.critic_feedback, 1):
            if feedback in availability:
                st.markdown(f'**Attempt {number} could not provide an accepted explanation**')
                st.text(availability[feedback])
            else:
                st.markdown(f'**Draft {number} was rejected**')
                st.text(explain_critic_feedback(feedback))


def main() -> None:
    st.set_page_config(page_title='Touchline / Broadcast Studio', layout='wide', initial_sidebar_state='collapsed')
    st.markdown(CSS, unsafe_allow_html=True)
    service = StudioService(os.getenv('API_BASE_URL') or None)
    from src.agents.groq_client import enabled, DEFAULT_MODEL
    real_local = enabled() and not service.api_base_url
    source = 'Local / Groq' if real_local else 'Remote API' if service.api_base_url else 'Local / offline'
    with st.container(key='studio_header'):
        title_column, help_column = st.columns([6, 1], vertical_alignment='center')
        title_column.markdown('<div class="studio-bar"><h1>Broadcast studio</h1></div>', unsafe_allow_html=True)
        with help_column.container(horizontal_alignment='right'):
            with st.popover('Help'):
                st.markdown('Use **Choose a play** above the episode metrics. Personalize the story in the right column. Select a **Key Events** milestone on the left '
                            'to inspect that moment; the final **Goal shot** milestone shows the complete sequence. '
                            'Episode metrics stay fixed while the pitch and overlays follow your selection. '
                            'Open **Test a review scenario** below the commentary to demonstrate a clean run, critic recovery or safe fallback.')
                st.markdown('The pitch shows authored synthetic positions at each event: eleven opponents '
                            'and the participating attackers. At the key pass, crosses show the separate '
                            'five-defender static reference used for packing. These positions are illustrative; '
                            'offside is not assessed.')
                st.caption(source + ' / Fictional players and events. Normalized coordinates.')
    with st.container(key='studio_controls'):
        try:
            ids = service.list_goal_ids()
        except StudioServiceError as error:
            html_card(escape(str(error)))
            return
        if not ids:
            html_card('No episodes loaded. Load synthetic episodes in the backend and refresh.')
            return
        st.markdown('<h2 class="section-heading">Choose a play</h2>', unsafe_allow_html=True)
        goal_id = st.selectbox('Choose a play', ids, key='episode', label_visibility='collapsed',
                               format_func=lambda value: EPISODE_LABELS.get(value, value))
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
    with st.container(key='studio_domains'):
        left, right = st.columns([1.65, 1], gap='medium')
    with left:
        tactical_slot = st.container(key='tactical_domain')
        history_slot = st.container(key='overlay_history')
    with right:
        st.markdown('<h2 class="section-heading">Why this goal happened</h2>', unsafe_allow_html=True)
        with st.container(key='narrative_controls'):
            narrative_controls = st.columns(3, vertical_alignment='bottom', gap='small')
            persona = narrative_controls[0].selectbox('Commentary style', list(PERSONA_LABELS), key='persona', format_func=PERSONA_LABELS.get)
            language = narrative_controls[1].selectbox('Language', ['en', 'es'], key='language', format_func=lambda value: 'English' if value == 'en' else 'Español')
            players = {event.player_id: event.player_name for event in episode.events}
            focus_id = narrative_controls[2].selectbox('Focus player', [None, *players, 'P_99'], key='focus',
                                    format_func=lambda player: 'Whole team' if player is None else players.get(player, 'External player / absent'))
        editorial_slot = st.container(key='editorial_domain')
        st.markdown('<h2 class="section-heading">Test a review scenario</h2>', unsafe_allow_html=True)
        with st.container(key='agent_controls', border=True):
            behavior_labels = dict(zip(DEMO_MODES, [
                'Generate commentary normally',
                'The first draft is rejected and corrected',
                'Both drafts are rejected and a fallback is used',
            ]))
            mode = st.selectbox('Agent behavior', DEMO_MODES, key='demo_mode',
                                         format_func=behavior_labels.get)
            demo_error = None
            if mode != 'Normal':
                options = available_demo_errors(episode)
                if st.session_state.get('demo_error') not in options:
                    st.session_state['demo_error'] = options[0]
                demo_error = st.selectbox('What should go wrong in the draft?', options, key='demo_error',
                                           format_func=DEMO_ERRORS.get)
                st.caption('This demonstration runs locally. An incorrect draft is deliberately introduced so the critic’s response can be inspected.')
        telemetry_slot = st.container(key='telemetry_domain')
        technical_slot = st.container(key='technical_details')
    # Session state survives script reruns; template edits must refresh cached text.
    template_revision = sha256(
        Path(narrator_module.__file__).read_bytes()
        + Path(__file__).with_name('service.py').read_bytes()
        + Path(__file__).with_name('demos.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'ingest/mock_generator.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'agents/orchestrator.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'agents/grounding.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'analytics/reconstruction.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'analytics/tactical_engine.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'analytics/sequence.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'analytics/evidence.py').read_bytes()
        + (Path(__file__).resolve().parents[1] / 'analytics/broadcast.py').read_bytes()
    ).hexdigest()
    key = (episode_key, persona, language, focus_id, mode, demo_error, template_revision,
           os.getenv('GROQ_MODEL', DEFAULT_MODEL) if real_local else None)
    generate = False
    if real_local and mode == 'Normal':
        with editorial_slot:
            generate = st.button('Generate commentary', key='generate_commentary', type='primary', width='stretch')
            st.caption('Uses the free model allowance only when requested. Identical validated results may be reused.')
            if generate:
                try:
                    with st.spinner('Your commentary is being prepared. This may take up to 20 seconds.'):
                        from src.ui.generation import generate_interactively
                        progress = st.empty()
                        try:
                            response = generate_interactively(
                                service, episode, persona=persona, language=language, focus_player_id=focus_id,
                                progress=lambda: progress.caption('Your commentary is being prepared.'))
                        finally:
                            progress.empty()
                    st.session_state['_groq_story'] = (key, response, persona, language)
                except StudioServiceError as error:
                    st.warning(str(error))
    try:
        cached = st.session_state.get('_broadcast')
        if (st.session_state.get('_result_key') != key or not hasattr(cached, 'reconstruction')
                or not hasattr(cached, 'tactical_evidence') or not hasattr(cached.telemetry, 'narrative_provider')):
            if real_local and mode == 'Normal':
                from src.agents.orchestrator import BroadcastOrchestrator
                from src.ingest.mock_generator import generate_mock_reconstruction
                st.session_state['_broadcast'] = BroadcastOrchestrator().run(
                    episode, persona=persona, language=language, focus_player_id=focus_id,
                    reconstruction=generate_mock_reconstruction(episode))
            else:
                st.session_state['_broadcast'] = service.broadcast(
                    episode, persona=persona, language=language, focus_player_id=focus_id, mode=mode,
                    demo_error=demo_error or 'invented_player',
                )
            st.session_state['_demo_review'] = service.demo_review
            st.session_state['_result_key'] = key
        result = st.session_state['_broadcast']
    except StudioServiceError as error:
        html_card(escape(str(error)))
        return
    story = st.session_state.get('_groq_story') if real_local and mode == 'Normal' else None
    commentary_result = story[1] if story else result
    commentary_persona, commentary_language = (story[2], story[3]) if story else (persona, language)
    telemetry = commentary_result.telemetry
    status = telemetry.status
    narrative_provider = PROVIDER_LABELS[telemetry.narrative_provider]
    generation_provider = PROVIDER_LABELS[telemetry.generation_provider]
    simulated = mode != 'Normal'
    analysis, metrics = result.analysis, result.broadcast_metrics
    pivot = next((event.player_name for event in episode.events if event.player_id == analysis.tactical_pivot), 'Unavailable')
    values = [
        ('Defenders bypassed', str(analysis.sequence_packing_score)), ('Key connector', pivot),
        ('Breakthrough zone', analysis.breakdown_zone or 'Unavailable'),
        ('Play rhythm', 'Fast transition' if metrics.tempo_classification == 'HIGH_TEMPO_CHAOS' else 'Controlled buildup' if metrics.tempo_classification else 'Unavailable'),
        ('Pass difficulty', f'{metrics.pass_difficulty:.1f} / 100' if metrics.pass_difficulty is not None else 'Unavailable'),
        ('Pass accuracy', f'{100*metrics.pass_accuracy:.0f}% ({metrics.successful_passes}/{metrics.total_passes})' if metrics.pass_accuracy is not None else 'Unavailable'),
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
                    with column:
                        st.button(f'{number}. +{milestone.relative_sec:.1f}s · {label}  \n'
                                  f'{milestone.player_name}',
                                  key=f'milestone_{milestone.event_id}',
                                  type='primary' if milestone.is_current else 'secondary',
                                  on_click=seek_replay, args=(milestone.relative_sec,), width='stretch', wrap=True)
        st.markdown('<h2 class="section-heading">Explore the play</h2>', unsafe_allow_html=True)
        figure = build_pitch_figure(result, clock)
        figure.update_layout(height=420)
        # HTML reflows the legend at narrow widths; pitch annotations remain on the plot.
        figure.layout.annotations = tuple(annotation for annotation in figure.layout.annotations
                                          if not (annotation.xref == 'paper' and annotation.yref == 'paper'))
        figure.update_layout(margin=dict(l=14, r=20, t=24, b=48))
        with st.container(key='pitch_surface'):
            legend = [('● Key pass', '#E8B86D'), ('◎ Focused player', '#76ADFF'),
                      ('✕ Bypassed defender', '#E58F94'), ('✕ Active defender', '#A6B0C3')]
            if result.reconstruction is not None:
                legend = [('● Key pass', '#E8B86D'), ('○ Opponents', '#A6B0C3'),
                          ('■ Goalkeeper', '#79C7B4'), ('● Attackers', '#E8ECF4')]
                if result.focus.participated:
                    legend.append(('◎ Focus', '#76ADFF'))
                if frame.events[-1].event.event_id == metrics.key_pass_event_id:
                    legend.extend([('✕ Bypassed reference', '#E58F94'), ('✕ Other reference', '#A6B0C3')])
            st.markdown('<div class="pitch-legend" aria-label="Pitch legend">' + ''.join(
                f'<span style="color:{color}" title="{escape("Participating attackers only" if label == "● Attackers" else label)}">{label}</span>'
                for label, color in legend
            ) + '</div>', unsafe_allow_html=True)
            st.plotly_chart(figure, width='stretch',
                            config={'displayModeBar': False, 'responsive': True}, theme=None, key='pitch')
        with st.container(key='pitch_note'):
            if result.reconstruction is not None:
                st.caption('Synthetic reconstruction · Offside not assessed')
            else:
                st.caption('Static packing reference · Offside not assessed')
        st.markdown('<h2 class="section-heading">On-screen facts at this moment</h2>', unsafe_allow_html=True)
        active_overlays = [item for item in frame.timed_overlays if item.is_active]
        history = [item for item in frame.timed_overlays if not item.is_active]
        summary = build_goal_summary(result, clock)
        if summary is not None:
            accuracy = (f'{100 * summary.pass_accuracy:.0f}% ({metrics.successful_passes}/{metrics.total_passes})'
                        if summary.pass_accuracy is not None else 'Unavailable')
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
    with editorial_slot:
        if real_local and mode == 'Normal':
            if story and story[0] != key:
                st.info('Your selections have changed. The previous commentary remains below; select Generate commentary to update it.')
                st.caption('Commentary play: ' + EPISODE_LABELS.get(commentary_result.episode.goal_id, 'Previously selected play'))
            elif not story:
                st.info('Select Generate commentary to request an AI explanation. A prepared explanation is shown for now.')
            if story and telemetry.status == 'DEGRADED_FALLBACK':
                st.warning('AI commentary is currently unavailable. A prepared explanation is shown instead.')
            if story and telemetry.cache_hit:
                st.caption('This explanation was generated previously and passed the checks. No new model request was needed.')
            if telemetry.model:
                st.caption(('Requested model: ' if telemetry.status == 'DEGRADED_FALLBACK' else 'Model: ') + telemetry.model)
        focus = commentary_result.focus
        story_analysis = commentary_result.analysis
        story_pivot = next((e.player_name for e in commentary_result.episode.events
                            if e.player_id == story_analysis.tactical_pivot), 'Unavailable')
        focus_text = ('Whole team' if focus.player_id is None else
                      f'{focus.player_name} · {len(focus.event_ids)} actions' if focus.participated else
                      'External player · absent')
        grounds = [('Packing', str(story_analysis.sequence_packing_score)), ('Tactical pivot', story_pivot),
                   ('Breakdown zone', story_analysis.breakdown_zone or 'Unavailable'), ('Tactical cause', story_analysis.tactical_cause)]
        chips = ''.join(f'<div class="fact-chip"><span class="caption">{label}</span><strong>{escape(value)}</strong></div>'
                        for label, value in grounds)
        html_card(f'<h2 class="narrative-headline">{escape(commentary_result.narrative.headline)}</h2>'
                  '<div class="editorial-badges">'
                  f'<span class="editorial-pill">{escape(PERSONA_LABELS[commentary_persona])} · {commentary_language.upper()}</span>'
                  f'<span class="editorial-pill">Focus: {escape(focus_text)}</span>'
                  f'<span class="editorial-pill">Source: {narrative_provider}</span></div>'
                  f'<p class="commentary">{escape(commentary_result.narrative.commentary)}</p>'
                  '<div class="verified-grounds"><div class="caption">Verified tactical grounds</div>'
                  f'<div class="fact-strip">{chips}</div>'
                  f'<span class="sr-only">{escape(commentary_result.narrative.tactical_breakdown)}</span></div>', 'editorial-card')
        with st.expander('Why these results?', expanded=False):
            explanations = build_analysis_explanations(commentary_result)
            if not explanations:
                st.caption('This API did not provide tactical evidence. No evidence has been inferred by the studio.')
            for title, body in explanations:
                with st.expander(title, expanded=False):
                    st.markdown(body)
    with telemetry_slot:
        with st.container(key='telemetry'):
            with st.expander('Step-by-step explanation', expanded=False):
                with st.container(border=True, key='review_facts'):
                    st.markdown('**1. The facts were established**')
                    st.caption('Tactical Analyst')
                    st.markdown(
                        f'The synthetic events were analysed, and **{story_pivot}** was selected as the key connector.'
                        if story_analysis.tactical_pivot else
                        'The synthetic events were analysed. No key connector could be identified from the available passing connections.'
                    )
                    st.markdown('These facts were kept unchanged throughout the review.')
                with st.container(border=True, key='review_checks'):
                    st.markdown('**2. The explanation was reviewed**' if telemetry.generation_provider == 'GROQ'
                                else '**2. A draft was prepared and checked**')
                    st.caption('Persona Narrator → Guardrail Critic')
                    if telemetry.generation_provider == 'GROQ' and telemetry.provider_calls == 0 and not telemetry.cache_hit:
                        st.markdown('AI generation was unavailable before a model draft could be requested. '
                                    'A prepared explanation was checked against the recorded facts instead.')
                    else:
                        st.markdown('The explanation was prepared using the selected style, language and player focus. '
                                    'Its participant names, event claims, numbers and required format were checked before display.')
                    if telemetry.critic_feedback:
                        render_critic_review(telemetry, st.session_state.get('_demo_review') if simulated else None)
                    else:
                        st.markdown('**No rejection was recorded.** The first draft passed the implemented checks.')
                with st.container(border=True, key='review_selection'):
                    st.markdown('**3. The final commentary was selected**')
                    if status == 'RECOVERED':
                        st.markdown('The rejection feedback was returned to the Persona Narrator. '
                                    'A second draft was generated from the same facts and passed validation.')
                        st.markdown('The corrected commentary is displayed above.')
                    elif status == 'DEGRADED_FALLBACK':
                        st.markdown('Both drafts were rejected. No further generation was attempted.' if simulated else
                                    'AI generation could not provide an accepted explanation within the available attempts and time.')
                        st.markdown('An offline fallback was assembled from verified participant names and tactical facts. '
                                    'It passed validation and is displayed above.')
                    else:
                        st.markdown('The accepted first draft is displayed above. No correction or fallback was needed.')
    with history_slot:
        if history:
            with st.expander(f'Earlier overlays ({len(history)})', expanded=False):
                for item in reversed(history):
                    render_overlay(item)
    with technical_slot:
        with st.expander('Technical details', expanded=False):
            st.caption('This walkthrough shows recorded steps and validation results. The implemented checks have a limited scope.')
            st.markdown(f'**Generator:** {generation_provider}')
            if telemetry.generation_latency_ms is not None:
                st.caption(f'Original generation and review: {telemetry.generation_latency_ms:.1f} ms. '
                           'Current request timing may include cache retrieval instead of inference.')
            if telemetry.model:
                st.caption(f'Model: {telemetry.model}. Provider calls: {telemetry.provider_calls}. '
                           f'Reused result: {telemetry.cache_hit}. Reported tokens: {telemetry.total_tokens}.')
            st.markdown(f'**Drafts requested:** {telemetry.attempts}  \n'
                        f'**Recorded handoffs:** {len(telemetry.handoffs)}  \n'
                        f'**Orchestration latency:** {telemetry.latency_ms:.2f} ms')
            st.caption('Local simulation timing does not represent Azure model latency.'
                       if simulated else f'Execution source: {source}.')
            if telemetry.critic_feedback:
                st.markdown('**Validator feedback**')
                for number, feedback in enumerate(telemetry.critic_feedback, 1):
                    st.caption(f'Draft {number}')
                    st.code(feedback, language=None, wrap_lines=True)
            st.markdown('**Recorded handoffs**')
            for handoff in telemetry.handoffs:
                st.markdown(f'**Attempt {handoff.attempt}:** '
                            f'{handoff.from_agent} → {handoff.to_agent}')
                st.text(handoff.reason)


if __name__ == '__main__':
    main()
