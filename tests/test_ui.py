"""Offline replay geometry, service boundaries and Streamlit interaction tests."""
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.service import DEMO_MODES, StudioService, StudioServiceError
from src.ui.visualization import build_pitch_figure, filter_synchronized_overlays

ROOT = Path(__file__).resolve().parents[1]


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
        for error in (HTTPError('url', 404, 'Missing', {}, None), URLError('offline'), TimeoutError()):
            with patch('src.ui.service.urlopen', side_effect=error):
                with self.assertRaises(StudioServiceError):
                    service.list_goal_ids()
        with patch.object(service, '_request', return_value={'wrong': 'shape'}):
            with self.assertRaises(StudioServiceError):
                service.list_goal_ids()
            with self.assertRaises(StudioServiceError):
                service.get_episode('missing')
        with patch('src.ui.service.urlopen', return_value=StringIO('["SYNTH_GOAL_01"]')):
            self.assertEqual(service.list_goal_ids(), ['SYNTH_GOAL_01'])


class StreamlitTests(unittest.TestCase):
    def test_offline_controls_replay_caching_and_recovery(self):
        original = StudioService.broadcast
        calls = []

        def counted(service, *args, **kwargs):
            calls.append(kwargs)
            return original(service, *args, **kwargs)

        with patch.dict('os.environ', {}, clear=True), patch.object(StudioService, 'broadcast', counted):
            app = AppTest.from_file(str(ROOT / 'src/ui/app.py'), default_timeout=15).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(calls), 1)
            duration = app.session_state['_broadcast'].episode.timestamp_goal - 1420.0
            self.assertAlmostEqual(app.slider(key='replay_clock').value, duration)
            app.button(key='key_pass').click().run()
            self.assertAlmostEqual(app.slider(key='replay_clock').value, 3.5)
            app.button(key='restart_replay').click().run()
            self.assertEqual(app.slider(key='replay_clock').value, 0.0)
            app.button(key='next_event').click().run()
            self.assertAlmostEqual(app.slider(key='replay_clock').value, 3.5)
            app.button(key='next_event').click().run()
            self.assertAlmostEqual(app.slider(key='replay_clock').value, 6.0)
            app.button(key='full_play').click().run()
            self.assertAlmostEqual(app.slider(key='replay_clock').value, duration)
            self.assertEqual(len(calls), 1, 'Replay buttons must reuse the narrative')
            app.slider(key='replay_clock').set_value(3.5).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(calls), 1, 'Moving the clock must not call the narrator')
            app.selectbox(key='focus').set_value('P_99').run()
            self.assertFalse(app.session_state['_broadcast'].focus.participated)
            app.selectbox(key='demo_mode').set_value(DEMO_MODES[1]).run()
            self.assertEqual(app.session_state['_broadcast'].telemetry.status, 'RECOVERED')
            app.selectbox(key='demo_mode').set_value(DEMO_MODES[2]).run()
            self.assertEqual(app.session_state['_broadcast'].telemetry.status, 'DEGRADED_FALLBACK')
            app.selectbox(key='episode').set_value('SYNTH_GOAL_03').run()
            self.assertEqual(app.session_state['_broadcast'].analysis.tactical_cause, 'Positional attack')
            app.selectbox(key='language').set_value('es').run()
            self.assertIn('Participantes verificados', app.session_state['_broadcast'].narrative.commentary)
            self.assertEqual(len(app.exception), 0)

    def test_remote_failure_is_actionable(self):
        with patch.dict('os.environ', {'API_BASE_URL': 'https://studio.example'}), patch.object(
            StudioService, 'list_goal_ids', side_effect=StudioServiceError('Cannot reach the API. Start the backend.')
        ):
            app = AppTest.from_file(str(ROOT / 'src/ui/app.py')).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('Cannot reach the API' in element.value for element in app.markdown))


if __name__ == '__main__':
    unittest.main()
