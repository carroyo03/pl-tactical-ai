"""Scoring-team coherence, transparent heuristics and compatible evidence enrichment."""
from copy import deepcopy
import unittest

from fastapi.testclient import TestClient

from src.agents.narrator import MockLLMClient
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.broadcast import compute_broadcast
from src.analytics.schemas import GoalEpisode
from src.analytics.tactical_engine import TacticalEngine
from src.api.app import create_app
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.service import parse_broadcast
from src.ui.visualization import build_analysis_explanations


class TacticalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.payload = generate_mock_episodes()[0]
        self.engine = TacticalEngine()

    def analyze(self):
        return self.engine.analyze_with_evidence(GoalEpisode.model_validate(self.payload))

    def test_canonical_evidence_matches_existing_metrics_and_snapshot(self):
        analysis, evidence = self.analyze()
        metrics, _ = compute_broadcast(GoalEpisode.model_validate(self.payload))
        self.assertEqual(evidence.key_pass_event_id, metrics.key_pass_event_id)
        key = evidence.passes[0]
        self.assertEqual(key.bypassed_defender_ids, ['DEF_01', 'DEF_02', 'DEF_03'])
        self.assertEqual([item.packing_score for item in evidence.passes], [3, 2])
        self.assertEqual(analysis.sequence_packing_score, 3, 'Packing remains MAX, not SUM')
        self.assertEqual(evidence.pivot_scores, {'P_04': 0.0, 'P_10': 0.5, 'P_09': 0.0})
        self.assertEqual(evidence.pivot_tied_player_ids, ['P_10'])
        self.assertEqual(evidence.cause_rule, 'SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS')
        self.assertAlmostEqual(evidence.duration_sec, 8.2)

    def test_rival_pass_cannot_set_packing_or_create_pivot_connections(self):
        self.payload['events'][1]['team'] = 'AWAY'
        analysis, evidence = self.analyze()
        metrics, _ = compute_broadcast(GoalEpisode.model_validate(self.payload))
        self.assertEqual(analysis.sequence_packing_score, 2)
        self.assertEqual(analysis.breakdown_zone, 'Attacking Third')
        self.assertEqual(evidence.key_pass_event_id, metrics.key_pass_event_id)
        self.assertEqual(evidence.key_pass_event_id, 'ev_03')
        self.assertEqual([item.event_id for item in evidence.passes], ['ev_03'])
        self.assertEqual([item.pass_event_id for item in evidence.inferred_connections], ['ev_03'])
        self.assertEqual(analysis.tactical_pivot, 'P_10')

    def test_rival_event_interrupts_recipient_inference_without_skipping_ahead(self):
        rival = dict(self.payload['events'][1], event_id='rival', player_id='R_01',
                     player_name='Fenn Ash', event_type='DEFENSIVE_DUEL', team='AWAY',
                     timestamp_sec=1424.0, is_successful=False)
        self.payload['events'].insert(2, rival)
        analysis, evidence = self.analyze()
        self.assertEqual([link.pass_event_id for link in evidence.inferred_connections], ['ev_03'])
        self.assertEqual(analysis.tactical_pivot, 'P_10')
        self.assertEqual(analysis.sequence_packing_score, 3)

    def test_recovery_requires_success_and_scoring_team_with_existing_precedence(self):
        for changes in ({'is_successful': False}, {'team': 'AWAY'}):
            with self.subTest(changes=changes):
                self.payload = generate_mock_episodes()[0]
                self.payload['events'][0].update(changes)
                analysis, evidence = self.analyze()
                self.assertEqual(analysis.tactical_cause, 'Central breakthrough through a vertical pass')
                self.assertEqual(evidence.cause_rule, 'PACKING_AT_LEAST_3')
        self.payload = generate_mock_episodes()[0]
        self.payload['timestamp_goal'] = 1430.0
        self.assertEqual(self.analyze()[1].cause_rule, 'SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS')
        self.payload['timestamp_goal'] = 1430.001
        self.assertEqual(self.analyze()[1].cause_rule, 'PACKING_AT_LEAST_3')

    def test_scoring_team_away_uses_the_same_normalized_attack_direction(self):
        self.payload['scoring_team'], self.payload['conceding_team'] = 'AWAY', 'HOME'
        for event in self.payload['events']:
            event['team'] = 'AWAY'
        analysis, evidence = self.analyze()
        self.assertEqual((analysis.sequence_packing_score, analysis.tactical_pivot), (3, 'P_10'))
        self.assertEqual(evidence.scoring_team, 'AWAY')

    def test_no_own_pass_has_no_pivot_key_or_positive_breakdown(self):
        for event in self.payload['events'][:-1]:
            event['team'] = 'AWAY'
        analysis, evidence = self.analyze()
        self.assertEqual(analysis.sequence_packing_score, 0)
        self.assertIsNone(analysis.tactical_pivot)
        self.assertIsNone(analysis.breakdown_zone)
        self.assertIsNone(evidence.key_pass_event_id)
        self.assertEqual(evidence.pivot_scores, {})
        self.assertEqual(evidence.cause_rule, 'DEFAULT_POSITIONAL')
        response = BroadcastOrchestrator().run(GoalEpisode.model_validate(self.payload))
        text = ' '.join(body for _, body in build_analysis_explanations(response))
        self.assertIn('No completed scoring-team pass', text)
        self.assertIn('no recorded pass attempts', text)

    def test_zero_packing_and_zero_centrality_ties_remain_explicit(self):
        self.payload['defenders_snapshot'] = []
        self.payload['events'] = self.payload['events'][2:]
        self.payload['events'][0]['player_id'] = 'Z'
        self.payload['events'][1]['player_id'] = 'A'
        analysis, evidence = self.analyze()
        self.assertEqual(analysis.tactical_pivot, 'Z')
        self.assertEqual(evidence.pivot_tied_player_ids, ['Z', 'A'])
        self.assertEqual(evidence.key_pass_event_id, 'ev_03')
        self.assertIsNone(analysis.breakdown_zone)
        response = BroadcastOrchestrator().run(GoalEpisode.model_validate(self.payload))
        self.assertIn('All scores are zero', ' '.join(body for _, body in build_analysis_explanations(response)))
        self.assertIn('chronological tie-break', response.narrative.commentary)

    def test_equal_timestamps_keep_input_order_for_key_and_graph(self):
        self.payload['defenders_snapshot'] = [dict(player_id='DEF_01', x=90.0, y=50.0)]
        self.payload['events'][1].update(timestamp_sec=1426.0, end_x=100.0)
        self.payload['events'][2].update(timestamp_sec=1426.0, end_x=100.0)
        self.payload['events'][1:3] = reversed(self.payload['events'][1:3])
        analysis, evidence = self.analyze()
        self.assertEqual(evidence.key_pass_event_id, 'ev_03')
        self.assertEqual(analysis.breakdown_zone, 'Attacking Third')
        self.assertEqual(evidence.inferred_connections[0].next_event_id, 'ev_02')
        self.assertEqual(compute_broadcast(GoalEpisode.model_validate(self.payload))[0].key_pass_event_id, 'ev_03')

    def test_failed_attempt_affects_accuracy_but_not_packing_or_graph(self):
        self.payload['events'][1]['is_successful'] = False
        response = BroadcastOrchestrator().run(GoalEpisode.model_validate(self.payload))
        self.assertEqual(response.analysis.sequence_packing_score, 2)
        self.assertEqual(response.broadcast_metrics.pass_accuracy, 0.5)
        self.assertEqual([item.event_id for item in response.tactical_evidence.passes], ['ev_03'])
        explanations = ' '.join(body for _, body in build_analysis_explanations(response))
        self.assertIn('completes 1 of its 2 attempted passes', explanations)

    def test_mixed_events_narrate_in_both_languages_without_changing_facts(self):
        self.payload['events'][0]['is_successful'] = False
        self.payload['events'][1]['team'] = 'AWAY'
        episode = GoalEpisode.model_validate(self.payload)
        before = deepcopy(episode.model_dump())
        for language in ('en', 'es'):
            response = BroadcastOrchestrator().run(episode, language=language)
            self.assertEqual(response.telemetry.status, 'SUCCESS')
            self.assertEqual(response.analysis.sequence_packing_score, 2)
            self.assertEqual(response.analysis.tactical_cause, 'Positional attack')
        self.assertEqual(episode.model_dump(), before)

    def test_optional_evidence_roundtrip_and_legacy_api_contract(self):
        with TestClient(create_app(client=MockLLMClient())) as http:
            path = '/goals/SYNTH_GOAL_01'
            legacy = http.get(path + '/intelligence').json()
            self.assertEqual(set(legacy), {'episode', 'analysis', 'narrative'})
            self.assertNotIn('tactical_evidence', legacy['analysis'])
            payload = http.get(path + '/broadcast').json()
        restored = parse_broadcast(payload, persona='TACTICAL_ANALYST', language='en')
        self.assertEqual(restored.tactical_evidence.version, 'tactical-evidence-v1')
        self.assertIn('DEF_01** is positioned at **X=50', ' '.join(body for _, body in build_analysis_explanations(restored)).replace('\\', ''))
        payload.pop('tactical_evidence')
        older = parse_broadcast(payload, persona='TACTICAL_ANALYST', language='en')
        self.assertIsNone(older.tactical_evidence)
        self.assertEqual(build_analysis_explanations(older), [])

    def test_client_cannot_mutate_evidence_and_retry_reuses_original_facts(self):
        episode = GoalEpisode.model_validate(self.payload)

        class MutatingClient:
            def __init__(self):
                self.contexts = []

            def generate(self, **kwargs):
                from src.agents.narrator import CreativeOutput

                self.contexts.append(deepcopy(kwargs['context']))
                kwargs['context']['tactical_evidence']['passes'][0]['packing_score'] = 999
                if len(self.contexts) == 1:
                    return CreativeOutput(headline='A draft', commentary='Missing all participant names.')
                return MockLLMClient().generate(**kwargs)

        client = MutatingClient()
        response = BroadcastOrchestrator(client).run(episode)
        self.assertEqual(response.telemetry.status, 'RECOVERED')
        self.assertEqual(response.tactical_evidence.passes[0].packing_score, 3)
        self.assertEqual(client.contexts[0]['tactical_evidence'], client.contexts[1]['tactical_evidence'])
        self.assertEqual(episode.model_dump(), self.payload)


if __name__ == '__main__':
    unittest.main()
