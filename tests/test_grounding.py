"""Explicit factual contradictions must fail before narrative publication."""
import unittest

from pydantic import ValidationError

from src.agents.narrator import CreativeOutput, MockLLMClient, PersonaNarrator
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.analytics.tactical_engine import TacticalEngine
from src.ingest.mock_generator import generate_mock_episodes


class DraftClient:
    def __init__(self, commentary):
        self.commentary = commentary
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return CreativeOutput(headline='The goal explained', commentary=self.commentary)
        return MockLLMClient().generate(**kwargs)


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        self.analysis = TacticalEngine().analyze(self.episode)

    def test_numeric_counts_and_known_roles_are_audited(self):
        drafts = [
            'Milo Arden finishes after five defenders are bypassed.',
            'Milo Arden remata después de superar a cinco defensores.',
            'Milo Arden supera a un defensor.',
            'Milo Arden supera a un rival.',
            'Milo Arden scores. Packing: -3.',
            'Milo Arden scores after a positional attack.',
            'Milo Arden scores. Packing score: 99.',
            'Milo Arden scores. Pass accuracy: 50%.',
            'Milo Arden scores. Pass distance: 99 pitch_units.',
            'Milo Arden scores. Pass difficulty: 12.',
            'Milo Arden scores after 999 seconds.',
            'Milo Arden scores from 37 meters.',
            'Nolan Vale is the tactical pivot. Milo Arden scores.',
            'Evan Rook scores after the move.',
            'Evan Rook then carries the ball. Milo Arden scores.',
            'Evan Rook luego conduce el balón. Milo Arden marca.',
            'Evan Rook plays the key pass. Milo Arden finishes.',
            'Milo Arden scores after a pass from the Defensive Third.',
        ]
        for draft in drafts:
            with self.subTest(draft=draft):
                client = DraftClient(draft)
                result = BroadcastOrchestrator(client).run(self.episode)
                self.assertEqual(result.telemetry.status, 'RECOVERED')
                self.assertEqual(result.telemetry.attempts, 2)
                self.assertTrue(result.telemetry.critic_feedback)
                self.assertEqual(client.calls[1]['context']['critic_feedback'], result.telemetry.critic_feedback)

    def test_valid_numeric_facts_and_roles_are_accepted(self):
        draft = ('Nolan Vale plays the key pass. Evan Rook is the tactical pivot. '
                 'Milo Arden scores after three defenders are bypassed. Pass accuracy: 100%.')
        result = BroadcastOrchestrator(DraftClient(draft)).run(self.episode)
        self.assertEqual(result.telemetry.status, 'SUCCESS')
        self.assertEqual(result.narrative.commentary, draft)

    def test_direct_narrator_uses_the_same_fact_audit(self):
        with self.assertRaises(ValidationError):
            PersonaNarrator(DraftClient('Milo Arden bypasses nine defenders.')).narrate(self.episode, self.analysis)

    def test_invented_actors_and_unrecorded_actions_trigger_repair(self):
        drafts = [
            'Milo Arden scores after Zorlan Phantom dribbles past the goalkeeper.',
            'Milo Arden marca después de que Zorlan Phantom regatea al portero.',
            'Milo Arden receives a pass from Zorlan Phantom.',
            'Milo Arden scores after Evan Rook wins possession.',
            'Milo Arden regatea y marca.',
            'Milo Arden scores after Nolan Vale shoots.',
            'Milo Arden scores. Evan Rook recupera el balón.',
            'Milo Arden passes to Nolan Vale.',
            'Nolan Vale passes to Milo Arden, who scores.',
            'Evan Rook pasa a Nolan Vale. Milo Arden marca.',
            'Milo Arden scores. The goal was scored by Evan Rook.',
            'Milo Arden marca. El gol fue marcado por Evan Rook.',
            'Milo Arden scores. The tactical pivot is Nolan Vale.',
            'Milo Arden scores. Evan Rook is the scorer.',
            'Milo Arden scores. Pass accuracy: 40%.',
            'Milo Arden scores. The team completed one of two passes.',
            'Milo Arden scores. Nolan Vale completes two of two passes.',
            'Milo Arden scores. Sequence duration: 3 seconds.',
            'Milo Arden scores. Ball speed: 3.',
        ]
        for draft in drafts:
            with self.subTest(draft=draft):
                client = DraftClient(draft)
                result = BroadcastOrchestrator(client).run(self.episode)
                self.assertEqual(result.telemetry.status, 'RECOVERED')
                self.assertEqual(result.telemetry.attempts, 2)
                self.assertEqual(result.analysis, self.analysis)
                self.assertEqual(len(result.telemetry.critic_feedback), 1)

    def test_recorded_actions_connections_and_individual_counts_are_accepted(self):
        drafts = [
            'Nolan Vale wins possession. Nolan Vale passes to Evan Rook. Milo Arden scores.',
            'Nolan Vale recupera el balón. Evan Rook pasa a Milo Arden. Milo Arden marca.',
            'Nolan Vale completes one of one passes. Milo Arden scores.',
            'The team completes two of two passes. Milo Arden scores.',
            'Milo Arden shoots. The goal was scored by Milo Arden.',
            'Milo Arden scores. Sequence duration: 8.2 seconds. Pass accuracy: 100%.',
            'Milo Arden scores. And Evan Rook passes to Milo Arden.',
            'After Milo Arden scores, the sequence ends.',
            'Cuando Milo Arden marca, termina la secuencia.',
            'Milo Arden scores after a pass from Middle Third.',
            "Milo Arden scores after a move built from Nolan Vale's pass.",
        ]
        for draft in drafts:
            with self.subTest(draft=draft):
                result = BroadcastOrchestrator(DraftClient(draft)).run(self.episode)
                self.assertEqual(result.telemetry.status, 'SUCCESS')
                self.assertEqual(result.narrative.commentary, draft)

    def test_failed_recovery_cannot_be_narrated_as_possession_won(self):
        payload = self.episode.model_dump()
        payload['events'][0]['is_successful'] = False
        episode = GoalEpisode.model_validate(payload)
        result = BroadcastOrchestrator(DraftClient('Nolan Vale wins possession. Milo Arden scores.')).run(episode)
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        self.assertNotIn('wins possession', result.narrative.commentary)

    def test_rival_event_prevents_claiming_a_pass_to_a_later_teammate(self):
        payload = self.episode.model_dump()
        payload['events'].insert(2, dict(payload['events'][1], event_id='rival', player_id='R_01',
                                        player_name='Fenn Ash', team='AWAY', event_type='DEFENSIVE_DUEL',
                                        timestamp_sec=1424.0, is_successful=False))
        result = BroadcastOrchestrator(DraftClient('Nolan Vale passes to Evan Rook. Milo Arden scores.')).run(
            GoalEpisode.model_validate(payload))
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        self.assertIn('recipient', result.telemetry.critic_feedback[0])

    def test_unknown_actor_in_headline_is_audited_separately(self):
        class HeadlineClient:
            def generate(self, **kwargs):
                return CreativeOutput(headline='Zorlan Phantom scores', commentary='Milo Arden scores.')

        result = BroadcastOrchestrator(HeadlineClient()).run(self.episode)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_FALLBACK')
        self.assertEqual(result.telemetry.attempts, 2)
        self.assertEqual(result.analysis, self.analysis)

    def test_direct_narrator_rejects_the_original_invented_player_example(self):
        with self.assertRaises(ValidationError):
            PersonaNarrator(DraftClient('Milo Arden scores after Zorlan Phantom dribbles past the goalkeeper.')).narrate(
                self.episode, self.analysis)

    def test_source_names_with_accents_apostrophes_and_digits_stay_valid(self):
        payload = self.episode.model_dump()
        renamed = {'Nolan Vale': "Noël D'Arcy", 'Evan Rook': 'Ilan Ash-Wren', 'Milo Arden': 'Milo 7'}
        for event in payload['events']:
            event['player_name'] = renamed[event['player_name']]
        for language in ('en', 'es'):
            for persona in ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER'):
                with self.subTest(language=language, persona=persona):
                    result = BroadcastOrchestrator().run(GoalEpisode.model_validate(payload),
                                                        language=language, persona=persona)
                    self.assertEqual(result.telemetry.status, 'SUCCESS')
                    self.assertIn('Milo 7', result.narrative.commentary)

    def test_reviewed_templates_cover_all_scenarios_personas_and_languages(self):
        for payload in generate_mock_episodes():
            for language in ('en', 'es'):
                comments = set()
                for persona in ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER'):
                    result = BroadcastOrchestrator().run(GoalEpisode.model_validate(payload),
                                                        persona=persona, language=language)
                    self.assertEqual(result.telemetry.status, 'SUCCESS')
                    self.assertNotIn('..', result.narrative.commentary)
                    self.assertNotRegex(result.narrative.commentary, r'[.!?]\s+(?:then|después)\b')
                    self.assertNotIn('crowd', result.narrative.commentary)
                    comments.add(result.narrative.commentary)
                self.assertEqual(len(comments), 3)

    def test_commentary_explains_static_and_inferred_evidence_without_causal_setup(self):
        for language in ('en', 'es'):
            result = BroadcastOrchestrator().run(self.episode, language=language)
            self.assertEqual(result.telemetry.status, 'SUCCESS')
            text = result.narrative.commentary
            self.assertIn('inferida' if language == 'es' else 'inferred', text)
            self.assertIn('No se mide su movimiento' if language == 'es' else 'movement during the pass is not measured', text)
            self.assertIn('mayor recuento' if language == 'es' else 'highest count', text)
            self.assertNotIn('setting up', text)

    def test_commentary_does_not_announce_a_goal_when_scorer_is_unidentified(self):
        payload = self.episode.model_dump()
        for event in payload['events']:
            if event['event_type'] == 'SHOT':
                event['is_successful'] = False
        for language in ('en', 'es'):
            result = BroadcastOrchestrator().run(GoalEpisode.model_validate(payload), language=language)
            self.assertEqual(result.telemetry.status, 'SUCCESS')
            self.assertNotIn('goal', result.narrative.headline.lower())
            self.assertNotIn('gol', result.narrative.headline.lower())
            self.assertIn('El goleador no está identificado.' if language == 'es' else 'The scorer is not identified.', result.narrative.commentary)


if __name__ == '__main__':
    unittest.main()
