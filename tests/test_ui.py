"""Offline replay geometry, service boundaries and Streamlit interaction tests."""
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import app_test as app_test_module

from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.service import DEMO_MODES, StudioService, StudioServiceError
from src.ui.visualization import (
    build_event_timeline, build_goal_summary, build_pitch_figure, filter_synchronized_overlays,
)

ROOT = Path(__file__).resolve().parents[1]


def tearDownModule():
    # AppTest owns a module-level TemporaryDirectory, even for file-based tests.
    # Explicitly release it after the last UI test instead of relying on GC.
    app_test_module.TMP_DIR.cleanup()


class VisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        cls.result = BroadcastOrchestrator().run(cls.episode, focus_player_id='P_04')

    def test_clock_boundaries_active_and_history(self):
        initial = filter_synchronized_overlays(self.result, 0.0)
        self.assertEqual(len(initial.events), 1)
        # Focused recovery is valid at t=0, while future pass metrics remain hidden.
        self.assertTrue(all(o.relative_sec == 0.0 for o in initial.timed_overlays))
        before = filter_synchronized_overlays(self.result, 3.49)
        self.assertEqual(len(before.events), 1)
        reached = filter_synchronized_overlays(self.result, 3.5)
        self.assertEqual(len(reached.events), 2)
        self.assertFalse(reached.events[0].is_active)
        self.assertTrue(reached.events[1].is_active)
        self.assertTrue(any(o.is_active and o.overlay.label == 'Pass distance' for o in reached.timed_overlays))
        self.assertTrue(all(o.relative_sec <= 3.5 for o in reached.timed_overlays))
        shot = filter_synchronized_overlays(self.result, initial.duration)
        self.assertEqual(len(shot.events), 4)
        self.assertFalse(any(o.is_active for o in shot.timed_overlays))

    def test_offsets_clamp_and_reject_nonfinite(self):
        self.assertEqual(filter_synchronized_overlays(self.result, -5).replay_offset_sec, 0.0)
        end = filter_synchronized_overlays(self.result, 999)
        self.assertEqual(end.replay_offset_sec, end.duration)
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                filter_synchronized_overlays(self.result, value)

    def test_pitch_no_future_highlighting_and_exact_axes(self):
        before = build_pitch_figure(self.result, 0.0)
        self.assertEqual(list(before.layout.xaxis.range), [0, 100])
        self.assertEqual(list(before.layout.yaxis.range), [0, 100])
        self.assertEqual(before.data[0].meta['bypassed'], [False] * 5)
        event_traces = [trace for trace in before.data if trace.meta.get('event_id')]
        self.assertEqual(len(event_traces), 1)
        key = build_pitch_figure(self.result, 3.5)
        self.assertEqual(key.data[0].meta['bypassed'], [True, True, True, False, False])
        key_traces = [trace for trace in key.data if trace.meta.get('is_key_pass')]
        self.assertEqual(len(key_traces), 1)
        self.assertTrue(key_traces[0].meta['is_focus'])
        boundaries = [shape.x0 for shape in key.layout.shapes if shape.type == 'line']
        self.assertIn(33.3, boundaries)
        self.assertIn(66.6, boundaries)
        self.assertEqual(len(build_pitch_figure(self.result).data), 5)

    def test_goal_summary_only_at_goal_with_consolidated_verified_values(self):
        duration = self.episode.timestamp_goal - self.episode.events[0].timestamp_sec
        self.assertIsNone(build_goal_summary(self.result, duration - 0.001))
        summary = build_goal_summary(self.result, duration)
        self.assertEqual(build_goal_summary(self.result, 8.2), summary)
        self.assertAlmostEqual(summary.duration_sec, 8.2)
        self.assertEqual(summary.pass_accuracy, 1.0)
        self.assertEqual(summary.maximum_packing, 3)
        self.assertEqual(summary.final_shooter, 'Milo Arden')
        self.assertEqual(build_goal_summary(self.result, 999), summary)

    def test_timeline_all_milestones_and_selected_state(self):
        initial = build_event_timeline(self.result, 0.0)
        self.assertEqual([step.label for step in initial], ['Recovery', 'Key pass', 'Pass', 'Goal shot'])
        for step, expected in zip(initial, [0.0, 3.5, 6.0, 8.2]):
            self.assertAlmostEqual(step.relative_sec, expected)
        self.assertEqual([step.is_reached for step in initial], [True, False, False, False])
        self.assertEqual([step.is_current for step in initial], [True, False, False, False])
        for index, offset in enumerate([0.0, 3.5, 6.0, initial[-1].relative_sec]):
            timeline = build_event_timeline(self.result, offset)
            self.assertEqual([step.event_id for step in timeline if step.is_current], [initial[index].event_id])
        between = build_event_timeline(self.result, 4.0)
        self.assertTrue(between[1].is_current)
        self.assertFalse(between[2].is_reached)

    def test_integrated_legend_and_honest_defender_tooltips(self):
        figure = build_pitch_figure(self.result, 3.5)
        annotations = ' '.join(annotation.text for annotation in figure.layout.annotations)
        for label in ('Key pass', 'Focused player', 'Bypassed defender', 'Active defender'):
            self.assertIn(label, annotations)
        defenders = figure.data[0]
        self.assertEqual(list(defenders.text), [d.player_id for d in self.episode.defenders_snapshot])
        self.assertIn('Bypassed', defenders.customdata[0][0])
        self.assertIn('Active', defenders.customdata[-1][0])
        self.assertNotIn('relative', defenders.hovertemplate)
        self.assertNotIn('+', defenders.hovertemplate)
        event = figure.data[2]
        self.assertIn('Nolan Vale', event.text[0])
        self.assertIn('+3.5s', event.text[0])
        self.assertIn('pitch_units', event.hovertemplate)

    def test_absent_focus_never_highlights_events(self):
        result = BroadcastOrchestrator().run(self.episode, focus_player_id='P_99')
        figure = build_pitch_figure(result)
        self.assertFalse(any(trace.meta.get('is_focus') for trace in figure.data))


class StudioServiceTests(unittest.TestCase):
    def test_episode_discovery_and_all_demo_modes(self):
        service = StudioService()
        ids = service.list_goal_ids()
        self.assertEqual(ids, ['SYNTH_GOAL_01', 'SYNTH_GOAL_02', 'SYNTH_GOAL_03'])
        episode = service.get_episode(ids[0])
        for mode, status, attempts in zip(DEMO_MODES, ['SUCCESS', 'RECOVERED', 'DEGRADED_FALLBACK'], [1, 2, 2]):
            response = service.broadcast(episode, mode=mode, focus_player_id='P_04')
            self.assertEqual(response.telemetry.status, status)
            self.assertEqual(response.telemetry.attempts, attempts)
            self.assertIn('Nolan Vale', response.narrative.commentary)
        with self.assertRaises(KeyError):
            service.get_episode('missing')

    def test_remote_broadcast_restores_grounding_and_encodes_parameters(self):
        episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        result = BroadcastOrchestrator().run(episode, focus_player_id='P_04')
        service = StudioService('https://studio.example/')
        with patch.object(service, '_request', return_value=result.model_dump()) as request:
            remote = service.broadcast(episode, focus_player_id='P_04')
            self.assertEqual(remote.narrative.commentary, result.narrative.commentary)
            self.assertIn('focus_player_id=P_04', request.call_args.args[0])
        # Demonstrations always run locally, even when the normal source is remote.
        with patch.object(service, '_request', side_effect=AssertionError('Unexpected network')):
            self.assertEqual(service.broadcast(episode, mode=DEMO_MODES[1]).telemetry.status, 'RECOVERED')

    def test_http_and_invalid_payload_errors(self):
        service = StudioService('https://studio.example')
        http_error = HTTPError('url', 404, 'Missing', {}, None)
        try:
            for error in (http_error, URLError('offline'), TimeoutError()):
                with patch('src.ui.service.urlopen', side_effect=error):
                    with self.assertRaises(StudioServiceError):
                        service.list_goal_ids()
        finally:
            http_error.close()
        with patch.object(service, '_request', return_value={'wrong': 'shape'}):
            with self.assertRaises(StudioServiceError):
                service.list_goal_ids()
            with self.assertRaises(StudioServiceError):
                service.get_episode('missing')
        with patch('src.ui.service.urlopen', return_value=StringIO('["SYNTH_GOAL_01"]')):
            self.assertEqual(service.list_goal_ids(), ['SYNTH_GOAL_01'])


class StreamlitTests(unittest.TestCase):
    def create_app_test(self):
        # Streamlit 1.66 initializes AppTest state on the bare unittest thread.
        # Capture and assert that specific SDK diagnostic, not application warnings.
        with self.assertLogs('streamlit.runtime.scriptrunner_utils.script_run_context', level='WARNING') as captured:
            app = AppTest.from_file(str(ROOT / 'src/ui/app.py'), default_timeout=15)
        self.assertTrue(captured.records)
        for record in captured.records:
            self.assertIn('missing ScriptRunContext', record.getMessage())
        return app

    def test_offline_controls_replay_caching_and_recovery(self):
        original = StudioService.broadcast
        calls = []

        def counted(service, *args, **kwargs):
            calls.append(kwargs)
            return original(service, *args, **kwargs)

        with patch.dict('os.environ', {}, clear=True), patch.object(StudioService, 'broadcast', counted):
            app = self.create_app_test().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(app.get('popover')), 1, 'Guide must be on demand, not a full-width banner')
            initial_markup = ' '.join(element.value for element in app.markdown)
            self.assertIn('Goal Sequence Summary', initial_markup)
            self.assertIn('Key Events', initial_markup)
            self.assertNotIn('[SYNTHETIC REPLAY]', initial_markup)
            self.assertNotIn('moment-pill', initial_markup)
            self.assertIn('<strong>Accepted</strong>', initial_markup)
            self.assertNotIn('No metric is triggered', initial_markup)
            self.assertIn('Tactical analyst · EN', initial_markup)
            self.assertEqual(len(app.sidebar.selectbox), 0)
            self.assertEqual(len(app.sidebar.button), 0)
            self.assertIn('Help', str(app.get('popover')[0].proto))
            self.assertEqual(app.selectbox(key='demo_mode').label, 'Agent behavior')
            self.assertEqual(app.selectbox(key='demo_mode').options, [
                'Clean run (first-pass success)', 'Single mistake (critic recovers)',
                'Repeated mistake (safe fallback)',
            ])
            self.assertIn('Focus: Whole team', initial_markup)
            self.assertIn('Packing</span><strong>3', initial_markup)
            for label in ('Tactical pivot', 'Breakdown zone', 'Tactical cause'):
                self.assertIn(label + '</span><strong>', initial_markup)
            for key in ('episode', 'persona', 'language', 'focus'):
                self.assertFalse(app.selectbox(key=key).proto.help)
            self.assertIn('Verified tactical grounds', initial_markup)
            self.assertNotIn('Validated creative commentary', initial_markup)
            self.assertNotIn('Computed by code', initial_markup)
            milestones = [button for button in app.button if button.key and button.key.startswith('milestone_')]
            self.assertEqual(len(milestones), 4)
            self.assertFalse(any(button.key in ('restart_replay', 'full_play') for button in app.button))
            initial_metrics = next(element.value for element in app.markdown if element.value.startswith('<div class="metrics">'))
            self.assertIn('39.8 / 100', initial_metrics)
            self.assertIn('100%', initial_metrics)
            self.assertIn('Goal shot', app.button(key='milestone_ev_04').label)
            self.assertIn('Current', app.button(key='milestone_ev_04').label)
            app.button(key='milestone_ev_02').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 3.5)
            self.assertNotIn('Goal Sequence Summary', ' '.join(element.value for element in app.markdown))
            self.assertIn('Current', app.button(key='milestone_ev_02').label)
            self.assertFalse(any(button.key and button.key.startswith('overlay_seek_') for button in app.button))
            self.assertFalse(any(button.label in ('Next event', 'View key pass') for button in app.button))
            app.button(key='milestone_ev_03').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 6.0)
            app.button(key='milestone_ev_02').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 3.5)
            self.assertEqual(len(calls), 1, 'Timeline jumps must not regenerate')
            duration = app.session_state['_broadcast'].episode.timestamp_goal - 1420.0
            app.button(key='milestone_ev_04').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], duration)
            app.button(key='milestone_ev_02').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 3.5)
            app.button(key='milestone_ev_01').click().run()
            self.assertEqual(app.session_state['replay_clock'], 0.0)
            zero_metrics = next(element.value for element in app.markdown if element.value.startswith('<div class="metrics">'))
            self.assertEqual(initial_metrics, zero_metrics, 'Episode metrics must stay constant throughout replay')
            self.assertNotIn('Upcoming:', zero_metrics)
            app.button(key='milestone_ev_02').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 3.5)
            app.button(key='milestone_ev_03').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], 6.0)
            app.button(key='milestone_ev_04').click().run()
            self.assertAlmostEqual(app.session_state['replay_clock'], duration)
            self.assertEqual(len(calls), 1, 'Replay buttons must reuse the narrative')
            self.assertFalse(app.slider, 'The four key events are the only replay controls')
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(calls), 1, 'Timeline jumps must not call the narrator')
            app.selectbox(key='focus').set_value('P_99').run()
            self.assertFalse(app.session_state['_broadcast'].focus.participated)
            app.selectbox(key='demo_mode').set_value(DEMO_MODES[1]).run()
            self.assertEqual(app.session_state['_broadcast'].telemetry.status, 'RECOVERED')
            recovered_markup = ' '.join(element.value for element in app.markdown)
            self.assertIn('Critic → Narrator', recovered_markup)
            self.assertIn('Draft 1 rejected by the critic', recovered_markup)
            self.assertIn('Repaired', recovered_markup)
            self.assertIn('Recovered after retry', recovered_markup)
            app.selectbox(key='demo_mode').set_value(DEMO_MODES[2]).run()
            self.assertEqual(app.session_state['_broadcast'].telemetry.status, 'DEGRADED_FALLBACK')
            self.assertIn('Fallback validated', ' '.join(element.value for element in app.markdown))
            self.assertIn('Safe fallback', ' '.join(element.value for element in app.markdown))
            app.selectbox(key='episode').set_value('SYNTH_GOAL_03').run()
            self.assertEqual(app.session_state['_broadcast'].analysis.tactical_cause, 'Positional attack')
            app.selectbox(key='language').set_value('es').run()
            self.assertIn('Participantes verificados', app.session_state['_broadcast'].narrative.commentary)
            self.assertEqual(len(app.exception), 0)

    def test_remote_failure_is_actionable(self):
        with patch.dict('os.environ', {'API_BASE_URL': 'https://studio.example'}), patch.object(
            StudioService, 'list_goal_ids', side_effect=StudioServiceError('Cannot reach the API. Start the backend.')
        ):
            app = self.create_app_test().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('Cannot reach the API' in element.value for element in app.markdown))


if __name__ == '__main__':
    unittest.main()
