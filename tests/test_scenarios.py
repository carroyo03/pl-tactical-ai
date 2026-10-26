"""Provider-agnostic review scenarios: the modifier alters drafts, the critic stays unchanged."""
import json
import unittest
from unittest.mock import patch

from src.agents.groq_client import GroqRuntime, MODELS, ProviderUnavailable
from src.agents.narrator import CreativeOutput, MockLLMClient
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.demos import DEMO_ERRORS, DraftModifier
from src.ui.service import DEMO_MODES, StudioService, build_review
from tests.test_groq import FakeTransport


def episodes():
    return [GoalEpisode.model_validate(payload) for payload in generate_mock_episodes()]


class RecordingClient(MockLLMClient):
    """Free-text provider that records the repair context it receives."""
    provider = 'GROQ'

    def __init__(self, failures=0):
        self.contexts, self.failures = [], failures

    def generate(self, *, system_prompt, context):
        self.contexts.append(context)
        if len(self.contexts) <= self.failures:
            raise ProviderUnavailable('provider_timeout', retryable=True)
        draft = super().generate(system_prompt=system_prompt, context=context)
        return CreativeOutput(headline=draft.headline,
                              commentary=draft.commentary + ' The pass accuracy was 100%. Sequence duration: 8.2 seconds.')


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict('os.environ', {'LLM_PROVIDER': ''})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_modifier_replaces_or_appends_without_keeping_both_versions(self):
        episode = episodes()[0]
        for error in DEMO_ERRORS:
            client = RecordingClient()
            modifier = DraftModifier(error, 1)
            result = BroadcastOrchestrator(client, modifier).run(episode)
            record = modifier.records[0]
            with self.subTest(error=error):
                self.assertTrue(record.applied, record.note)
                self.assertNotEqual(record.original, record.altered)
                self.assertEqual(result.telemetry.status, 'RECOVERED')
                if error == 'wrong_accuracy':
                    self.assertNotIn('100%', record.altered[1])
                if error == 'missing_names':
                    for name in (context := client.contexts[0])['scorer_name'], context['pivot_name']:
                        self.assertNotIn(name, record.altered[1])

    def test_repair_request_carries_the_rejected_text_and_facts_are_unchanged(self):
        episode = episodes()[0]
        baseline = BroadcastOrchestrator(MockLLMClient()).run(episode)
        client = RecordingClient()
        modifier = DraftModifier('invented_player', 1)
        result = BroadcastOrchestrator(client, modifier).run(episode)
        self.assertNotIn('rejected_draft', client.contexts[0])
        self.assertIn('Zorlan Phantom', client.contexts[1]['rejected_draft']['commentary'])
        self.assertTrue(client.contexts[1]['critic_feedback'])
        self.assertEqual(result.analysis, baseline.analysis)
        self.assertEqual(result.broadcast_metrics, baseline.broadcast_metrics)
        self.assertEqual(result.episode, episode)
        self.assertFalse(modifier.records[1].targeted)

    def test_double_alteration_ends_in_validated_fallback(self):
        modifier = DraftModifier('wrong_duration', 2)
        result = BroadcastOrchestrator(RecordingClient(), modifier).run(episodes()[0])
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        review = build_review(modifier, result, 'wrong_duration')
        self.assertEqual(review.scenario_status, 'COMPLETED')
        self.assertEqual(len(review.rejected_drafts), 2)
        self.assertTrue(all(item.modification_applied for item in review.attempts))

    def test_unavailable_provider_is_not_executed_not_completed(self):
        client = RecordingClient(failures=2)
        modifier = DraftModifier('invented_player', 1)
        result = BroadcastOrchestrator(client, modifier).run(episodes()[0])
        review = build_review(modifier, result, 'invented_player')
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(review.scenario_status, 'NOT_EXECUTED')
        self.assertTrue(all(item.original_commentary is None for item in review.attempts))
        self.assertEqual(review.rejected_drafts, ())

    def test_first_failure_alters_the_first_usable_draft_and_says_no_correction_remained(self):
        modifier = DraftModifier('invented_player', 1)
        result = BroadcastOrchestrator(RecordingClient(failures=1), modifier).run(episodes()[0])
        review = build_review(modifier, result, 'invented_player')
        self.assertEqual(review.scenario_status, 'COMPLETED')
        self.assertIn('no correction attempt remained', review.scenario_note)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')

    def test_unreliable_modification_is_recorded_as_not_applied(self):
        episode = episodes()[0]
        modifier = DraftModifier('missing_names', 1)
        client = RecordingClient()
        client.generate = lambda *, system_prompt, context: CreativeOutput(headline='A move', commentary='A neat move ends in a goal.')
        result = BroadcastOrchestrator(client, modifier).run(episode)
        self.assertFalse(modifier.records[0].applied)
        review = build_review(modifier, result, 'missing_names')
        self.assertEqual(review.scenario_status, 'NOT_EXECUTED')

    def test_groq_runtime_runs_scenarios_with_at_most_two_calls_and_no_cache(self):
        episode = episodes()[0]
        for modifier_args, status in ((('invented_player', 1), 'RECOVERED'), (('wrong_recipient', 2), 'DEGRADED_FALLBACK')):
            runtime = GroqRuntime('unused', MODELS[0], transport=FakeTransport())
            for run in (1, 2):
                modifier = DraftModifier(*modifier_args)
                result = runtime.run(episode, modifier=modifier)
                with self.subTest(args=modifier_args, run=run):
                    self.assertEqual(result.telemetry.status, status)
                    self.assertFalse(result.telemetry.cache_hit)
                    self.assertEqual(result.telemetry.provider_calls, 2)
            self.assertEqual(len(runtime.transport.calls), 4)
            repair = json.loads(runtime.transport.calls[1][0]['messages'][1]['content'])
            self.assertIn('rejected_draft', repair)
            self.assertEqual(runtime.cache, {})

    def test_service_uses_the_active_provider_for_scenarios(self):
        service = StudioService()
        runtime = GroqRuntime('unused', MODELS[0], transport=FakeTransport())
        with patch.dict('os.environ', {'LLM_PROVIDER': 'groq'}), patch(
                'src.agents.groq_client.local_runtime', return_value=runtime):
            result = service.broadcast(episodes()[0], mode=DEMO_MODES[1], demo_error='wrong_duration')
        self.assertEqual(result.telemetry.generation_provider, 'GROQ')
        self.assertEqual(service.demo_review.attempts[0].provider, 'GROQ')
        self.assertEqual(service.demo_review.scenario_status, 'COMPLETED')

    def test_remote_configuration_without_groq_keeps_scenarios_offline(self):
        service = StudioService('https://example.invalid')
        with patch.object(service, '_request', side_effect=AssertionError('no remote request')):
            result = service.broadcast(episodes()[0], mode=DEMO_MODES[1])
        self.assertEqual(result.telemetry.generation_provider, 'OFFLINE_MOCK')

    def test_remote_episodes_with_studio_side_groq_never_call_the_remote_broadcast(self):
        service = StudioService('https://example.invalid')
        runtime = GroqRuntime('unused', MODELS[0], transport=FakeTransport())
        with patch.dict('os.environ', {'LLM_PROVIDER': 'groq'}), patch(
                'src.agents.groq_client.local_runtime', return_value=runtime), patch.object(
                service, '_request', side_effect=AssertionError('generation must stay in the studio')):
            normal = service.broadcast(episodes()[0])
            scenario = service.broadcast(episodes()[0], mode=DEMO_MODES[2], demo_error='wrong_accuracy')
        self.assertEqual(normal.telemetry.generation_provider, 'GROQ')
        self.assertEqual(scenario.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(service.demo_review.scenario_status, 'COMPLETED')


if __name__ == '__main__':
    unittest.main()


class ScenarioRegressionTests(unittest.TestCase):
    def test_unalterable_first_draft_does_not_use_up_the_quota(self):
        client = RecordingClient()
        original = client.generate
        calls = []

        def generate(*, system_prompt, context):
            calls.append(1)
            if len(calls) == 1:
                return CreativeOutput(headline='A move', commentary='The sequence ends in a goal.')
            return original(system_prompt=system_prompt, context=context)
        client.generate = generate
        modifier = DraftModifier('missing_names', 1)
        BroadcastOrchestrator(client, modifier).run(episodes()[0])
        self.assertFalse(modifier.records[0].applied)
        self.assertTrue(modifier.records[1].targeted and modifier.records[1].applied)
