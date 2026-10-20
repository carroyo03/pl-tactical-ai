"""Synthetic scenarios, geometry, orchestration recovery and HTTP integration."""
from copy import deepcopy
from math import hypot, sqrt
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from src.agents.narrator import CreativeOutput, MockLLMClient, NarrativeGenerationError
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.broadcast import compute_broadcast
from src.analytics.schemas import GoalEpisode
from src.analytics.tactical_engine import TacticalEngine
from src.api.app import create_app
from src.ingest.mock_generator import generate_mock_episodes, generate_mock_goal_episode


class ScriptedClient:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        # Simulate untrusted creative text bypassing client-side validation.
        return CreativeOutput.model_construct(headline=output[0], commentary=output[1])


class BroadcastTests(unittest.TestCase):
    def setUp(self):
        self.payloads = generate_mock_episodes()
        self.episode = GoalEpisode.model_validate(self.payloads[0])

    def test_reproducible_three_causes(self):
        self.assertEqual(self.payloads, generate_mock_episodes())
        expected = ['Quick transition after recovery', 'Central breakthrough through a vertical pass', 'Positional attack']
        for payload, cause in zip(self.payloads, expected):
            result = BroadcastOrchestrator().run(GoalEpisode.model_validate(payload))
            self.assertEqual(result.analysis.tactical_cause, cause)
            self.assertEqual(result.telemetry.status, 'SUCCESS')
        with TemporaryDirectory() as directory:
            self.assertEqual(generate_mock_goal_episode(directory), self.payloads)

    def test_metric_formulas_and_overlay_units(self):
        metrics, focus = compute_broadcast(self.episode, 'P_04')
        self.assertAlmostEqual(metrics.pass_distance_units, hypot(37, 7))
        expected = 40 * hypot(37, 7) / (100 * sqrt(2)) + 30 * .37 + 30 * .6
        self.assertAlmostEqual(metrics.pass_difficulty, expected)
        self.assertEqual(metrics.pass_accuracy, 1.0)
        self.assertEqual((metrics.successful_passes, metrics.total_passes), (2, 2))
        self.assertAlmostEqual(metrics.tempo_events_per_sec, 4 / 8.2)
        self.assertAlmostEqual(metrics.vertical_progression_rate, 53 / 8.2)
        self.assertEqual(metrics.tempo_classification, 'HIGH_TEMPO_CHAOS')
        self.assertTrue(focus.participated)
        self.assertEqual(len(focus.event_ids), 2)
        self.assertTrue(any(o.is_focus for o in metrics.timed_overlays))
        self.assertEqual({o.unit for o in metrics.timed_overlays}, {'pitch_units', 'score', '%'})
        self.assertEqual([o.timestamp_sec for o in metrics.timed_overlays], sorted(o.timestamp_sec for o in metrics.timed_overlays))

    def test_no_passes_zero_duration_and_missing_destination_y(self):
        payload = deepcopy(self.payloads[0])
        payload['events'] = payload['events'][-1:]
        result, _ = compute_broadcast(GoalEpisode.model_validate(payload))
        self.assertIsNone(result.pass_accuracy)
        self.assertIsNone(result.pass_distance_units)
        self.assertIsNone(result.tempo_events_per_sec)
        self.assertIsNone(result.vertical_progression_rate)
        self.assertIsNone(result.tempo_classification)
        payload = deepcopy(self.payloads[0])
        payload['events'][1]['end_y'] = None
        result, _ = compute_broadcast(GoalEpisode.model_validate(payload))
        self.assertIsNone(result.pass_distance_units)
        self.assertIsNone(result.pass_difficulty)

    def test_accuracy_includes_failed_scoring_passes_only(self):
        payload = deepcopy(self.payloads[0])
        payload['events'][2]['is_successful'] = False
        result, _ = compute_broadcast(GoalEpisode.model_validate(payload))
        self.assertEqual(result.pass_accuracy, .5)
        payload['events'][2]['team'] = 'AWAY'
        result, _ = compute_broadcast(GoalEpisode.model_validate(payload))
        self.assertEqual(result.pass_accuracy, 1.0)
        self.assertEqual(result.total_passes, 1)

    def test_success_first_attempt_with_focus(self):
        result = BroadcastOrchestrator().run(self.episode, focus_player_id='P_04')
        self.assertEqual(result.telemetry.attempts, 1)
        self.assertEqual(result.telemetry.status, 'SUCCESS')
        self.assertEqual(result.telemetry.critic_feedback, [])
        self.assertEqual(len(result.telemetry.handoffs), 2)
        self.assertIn('Nolan Vale', result.narrative.commentary)
        self.assertGreater(result.telemetry.latency_ms, 0)

    def test_real_retry_receives_feedback(self):
        client = ScriptedClient([
            ('A goal', 'Milo Arden appears in P_09.'),
            ('A verified goal', 'Milo Arden and Nolan Vale feature in this sequence.'),
        ])
        result = BroadcastOrchestrator(client).run(self.episode, focus_player_id='P_04')
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        self.assertEqual(result.telemetry.attempts, 2)
        self.assertEqual(len(client.calls), 2)
        self.assertIn('Internal IDs', result.telemetry.critic_feedback[0])
        self.assertEqual(client.calls[1]['context']['critic_feedback'], result.telemetry.critic_feedback)
        self.assertIn('Repair', client.calls[1]['system_prompt'])
        self.assertEqual(len(result.telemetry.handoffs), 4)

    def test_double_failure_validated_fallback(self):
        client = ScriptedClient([('A goal', 'No names here.'), ('Another goal', 'Still no names.')])
        result = BroadcastOrchestrator(client).run(self.episode, language='es', focus_player_id='P_04')
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(result.telemetry.attempts, 2)
        self.assertEqual(len(result.telemetry.critic_feedback), 2)
        self.assertIn('Nolan Vale', result.narrative.commentary)
        self.assertIn('Milo Arden', result.narrative.commentary)
        self.assertIn('tercio medio', result.narrative.tactical_breakdown)
        self.assertEqual(result.analysis, TacticalEngine().analyze(self.episode))
        self.assertEqual(len(client.calls), 2)

    def test_focus_omission_is_critic_error_and_absence_is_explicit(self):
        client = ScriptedClient([('A goal', 'Milo Arden features here.'),
                                 ('A goal', 'Milo Arden and Nolan Vale feature here.')])
        result = BroadcastOrchestrator(client).run(self.episode, focus_player_id='P_04')
        self.assertIn('participating focus player: Nolan Vale', result.telemetry.critic_feedback[0])
        absent = BroadcastOrchestrator().run(self.episode, focus_player_id='P_MISSING')
        self.assertFalse(absent.focus.participated)
        self.assertIsNone(absent.focus.player_name)
        self.assertEqual(absent.focus.event_ids, [])
        self.assertFalse(any(o.is_focus for o in absent.broadcast_metrics.timed_overlays))

    def test_refusal_recovers_but_programming_errors_propagate(self):
        client = ScriptedClient([NarrativeGenerationError('Refused'), ('A goal', 'Milo Arden appears here.')])
        result = BroadcastOrchestrator(client).run(self.episode)
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        with self.assertRaises(RuntimeError):
            BroadcastOrchestrator(ScriptedClient([RuntimeError('Bug')])).run(self.episode)

    def test_shared_orchestrator_keeps_requests_isolated(self):
        orchestrator = BroadcastOrchestrator()
        first = orchestrator.run(self.episode, focus_player_id='P_04')
        second = orchestrator.run(self.episode)
        self.assertFalse(second.focus.participated)
        self.assertEqual(second.telemetry.attempts, 1)
        self.assertIn('Nolan Vale', first.narrative.commentary)
        self.assertNotIn('Featured involvement', second.narrative.commentary)


class BroadcastAPITests(unittest.TestCase):
    def test_discovery_compatibility_and_broadcast(self):
        with TestClient(create_app(client=MockLLMClient())) as http:
            ids = http.get('/goals').json()
            self.assertEqual(ids, ['SYNTH_GOAL_01', 'SYNTH_GOAL_02', 'SYNTH_GOAL_03'])
            for goal_id in ids:
                legacy = http.get(f'/goals/{goal_id}/intelligence')
                self.assertEqual(legacy.status_code, 200)
                self.assertEqual(set(legacy.json()), {'episode', 'analysis', 'narrative'})
                broadcast = http.get(f'/goals/{goal_id}/broadcast', params={'focus_player_id': 'P_04'})
                self.assertEqual(broadcast.status_code, 200)
                self.assertTrue(broadcast.json()['focus']['participated'])
                self.assertEqual(broadcast.json()['telemetry']['status'], 'SUCCESS')
            self.assertEqual(http.get('/goals/missing/broadcast').status_code, 404)
            self.assertEqual(http.get(f'/goals/{ids[0]}/broadcast?language=fr').status_code, 422)
            self.assertEqual(http.get(f'/goals/{ids[0]}/broadcast?persona=bad').status_code, 422)


if __name__ == '__main__':
    unittest.main()
