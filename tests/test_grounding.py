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


if __name__ == '__main__':
    unittest.main()
