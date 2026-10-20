"""Offline tests; no Azure credentials or network required."""
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from src.agents.narrator import (
    AzureOpenAIClient, CreativeOutput, MockLLMClient, NarrativeOutput, PersonaNarrator,
)
from src.analytics.schemas import GoalEpisode
from src.analytics.tactical_engine import TacticalEngine


def sample_episode():
    events = []
    for index, (player, name, kind, time, start, end) in enumerate([
        ('P_04', 'Caicedo', 'RECOVERY', 0.0, 35.0, 35.0),
        ('P_04', 'Caicedo', 'PASS', 2.0, 35.0, 72.0),
        ('P_10', 'Palmer', 'PASS', 5.0, 72.0, 88.0),
        ('P_09', 'Jackson', 'SHOT', 8.2, 88.0, 100.0),
    ]):
        events.append(dict(event_id=f'ev_{index:02}', match_id='MATCH_01', timestamp_sec=time,
                           period=1, team='HOME', player_id=player, player_name=name,
                           event_type=kind, start_x=start, start_y=50.0, end_x=end,
                           end_y=50.0, is_successful=True))
    return GoalEpisode.model_validate(dict(
        goal_id='GOAL_01', match_id='MATCH_01', timestamp_goal=8.2,
        scoring_team='HOME', conceding_team='AWAY', events=events,
        defenders_snapshot=[dict(player_id=f'DEF_{i}', x=x, y=50.0)
                            for i, x in enumerate([50.0, 52.0, 65.0, 78.0, 80.0])],
    ))


class StubClient:
    def __init__(self, **overrides):
        self.values = dict(headline='Palmer unlocks the sequence', commentary='Palmer features in the goal sequence.')
        self.values.update(overrides)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return CreativeOutput.model_construct(**self.values)


class NarratorTests(unittest.TestCase):
    def setUp(self):
        self.episode = sample_episode()
        self.analysis = TacticalEngine().analyze(self.episode)

    def test_all_personas_and_languages_offline(self):
        narrator = PersonaNarrator()
        self.assertIsInstance(narrator.client, MockLLMClient)
        for language in ('en', 'es'):
            comments = set()
            for persona in ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER'):
                result = narrator.narrate(self.episode, self.analysis, persona=persona, language=language)
                self.assertIsInstance(result, NarrativeOutput)
                self.assertIn('Jackson', result.commentary)
                self.assertIn('Palmer', result.commentary)
                self.assertIn('3', result.commentary)
                self.assertNotRegex(result.commentary, r'(?:^|[.!?]\s+)(?:then|después)\b')
                self.assertIn('instantánea defensiva' if language == 'es' else 'defensive snapshot', result.commentary)
                self.assertLess(result.commentary.index('Caicedo'), result.commentary.index('Jackson'))
                self.assertIn('Palmer', result.tactical_breakdown)
                self.assertIn('3', result.tactical_breakdown)
                self.assertNotIn('P_10', result.model_dump_json())
                self.assertLessEqual(len(result.headline.split()), 12)
                comments.add(result.commentary)
            self.assertEqual(len(comments), 3)

    def test_localized_breakdown_is_deterministic(self):
        client = StubClient()
        narrator = PersonaNarrator(client)
        result = narrator.narrate(self.episode, self.analysis)
        self.assertEqual(result.tactical_breakdown,
                         'Maximum packing per pass: 3. Tactical pivot: Palmer. '
                         'Breakdown zone: Middle Third. Tactical cause: Quick transition after recovery.')
        spanish = narrator.narrate(self.episode, self.analysis, language='es')
        self.assertIn('tercio medio', spanish.tactical_breakdown)
        self.assertIn('Transición rápida tras recuperación', spanish.tactical_breakdown)
        self.assertEqual(client.calls[0]['context']['players']['P_10'], 'Palmer (P_10)')

    def test_chronology_and_goal_author(self):
        payload = self.episode.model_dump()
        payload['events'].reverse()
        episode = GoalEpisode.model_validate(payload)
        client = StubClient(commentary='Jackson finishes this sequence.')
        PersonaNarrator(client).narrate(episode, self.analysis)
        context = client.calls[0]['context']
        self.assertEqual(context['scorer_name'], 'Jackson')
        self.assertEqual([e['timestamp_sec'] for e in context['events']], [0.0, 2.0, 5.0, 8.2])

    def test_headline_word_boundary(self):
        for count in (12, 13):
            narrator = PersonaNarrator(StubClient(headline=' '.join(['word'] * count)))
            if count == 12:
                narrator.narrate(self.episode, self.analysis)
            else:
                with self.assertRaises(ValidationError):
                    narrator.narrate(self.episode, self.analysis)

    def test_guardrails_reject_invalid_model_output(self):
        invalid = [
            {'commentary': 'A great goal!'},
            {'commentary': 'Palmerston drives the attack.'},
            {'commentary': 'Palmer (P_10) plays the pass.'},
            {'commentary': 'Jackson appears in ev_02.'},
            {'commentary': 'Jackson appears in P_999.'},
            {'commentary': 'Jackson appears in MATCH_01.'},
            {'headline': 'Palmer P_10 unlocks the sequence'},
            {'headline': '   '}, {'commentary': '   '},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                PersonaNarrator(StubClient(**values)).narrate(self.episode, self.analysis)

    def test_model_cannot_supply_breakdown(self):
        with self.assertRaises(ValidationError):
            CreativeOutput.model_validate(dict(headline='A goal', commentary='Jackson scores.',
                                               tactical_breakdown='Invented score: 99'))

    def test_unknown_pivot_and_invalid_options_fail_before_client(self):
        client = StubClient()
        narrator = PersonaNarrator(client)
        for options in ({'language': 'fr'}, {'persona': 'UNKNOWN'}):
            with self.assertRaises(ValidationError):
                narrator.narrate(self.episode, self.analysis, **options)
        analysis = self.analysis.model_copy(update={'tactical_pivot': 'MISSING'})
        with self.assertRaises(ValueError):
            narrator.narrate(self.episode, analysis)
        self.assertEqual(client.calls, [])

    def test_null_pivot_and_zero_packing(self):
        payload = self.episode.model_dump()
        payload['events'] = payload['events'][-1:]
        episode = GoalEpisode.model_validate(payload)
        analysis = TacticalEngine().analyze(episode)
        result = PersonaNarrator().narrate(episode, analysis)
        self.assertIn('Maximum packing per pass: 0', result.tactical_breakdown)
        self.assertIn('unavailable', result.tactical_breakdown)
        self.assertIn('no breakdown zone', result.tactical_breakdown)
        self.assertIn('Jackson', result.commentary)

    def test_azure_adapter_structured_request_and_refusal(self):
        requests = []
        message = SimpleNamespace(parsed=CreativeOutput(headline='A goal sequence', commentary='Jackson scores.'), refusal=None)
        choice = SimpleNamespace(message=message, finish_reason='stop')

        def parse(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[choice])

        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        narrator = PersonaNarrator(AzureOpenAIClient(sdk, 'my-gpt4o-deployment'))
        narrator.narrate(self.episode, self.analysis)
        self.assertIs(requests[0]['response_format'], CreativeOutput)
        self.assertEqual(requests[0]['model'], 'my-gpt4o-deployment')
        self.assertEqual(set(CreativeOutput.model_fields), {'headline', 'commentary'})
        for refusal, parsed, reason in [('refused', None, 'stop'), (None, None, 'stop'),
                                        (None, message.parsed, 'length')]:
            message.refusal, message.parsed, choice.finish_reason = refusal, parsed, reason
            with self.assertRaises(ValueError):
                narrator.narrate(self.episode, self.analysis)


if __name__ == '__main__':
    unittest.main()
