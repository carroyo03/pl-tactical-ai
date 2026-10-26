"""Studio-side Azure OpenAI: explicit opt-in, shared writing request, scenarios, no credentials."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx2
from openai import AuthenticationError

from src.agents import azure_runtime
from src.agents.azure_runtime import AzureRuntime, azure_settings
from src.agents.narrator import CreativeOutput
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.demos import DraftModifier
from src.ui.service import DEMO_MODES, StudioService, StudioServiceError, active_model, active_provider

ENVIRONMENT = {'LLM_PROVIDER': 'azure', 'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com',
               'AZURE_OPENAI_DEPLOYMENT': 'unit-deployment', 'AZURE_OPENAI_AUTH': 'entra'}


def episode():
    return GoalEpisode.model_validate(generate_mock_episodes()[0])


def echoing_sdk():
    """Fake SDK whose model rewrites the supplied verified reference verbatim."""
    def parse(**kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        parsed = CreativeOutput.model_validate(context['verified_reference'])
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=250), choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(refusal=None, parsed=parsed))])
    parse_mock = Mock(side_effect=parse)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse_mock))), parse_mock


class AzureRuntimeTests(unittest.TestCase):
    def test_provider_is_an_explicit_opt_in_and_respects_the_paid_model_switch(self):
        with patch.dict('os.environ', ENVIRONMENT, clear=True):
            self.assertEqual(active_provider(), 'AZURE_OPENAI')
            self.assertEqual(active_model(), 'unit-deployment')
            self.assertTrue(azure_settings().entra)
        for change in ({'LLM_PROVIDER': ''}, {'DISABLE_PAID_MODELS': 'true'}, {'AZURE_OPENAI_AUTH': ''},
                       {'AZURE_OPENAI_DEPLOYMENT': ''}):
            with self.subTest(change=change), patch.dict('os.environ', {**ENVIRONMENT, **change}, clear=True):
                self.assertIsNone(active_provider())

    def test_normal_run_records_deployment_calls_and_tokens(self):
        sdk, parse = echoing_sdk()
        result = AzureRuntime(sdk, 'unit-deployment').run(episode(), language='es')
        self.assertEqual(result.telemetry.status, 'SUCCESS')
        self.assertEqual(result.telemetry.generation_provider, 'AZURE_OPENAI')
        self.assertEqual((result.telemetry.model, result.telemetry.provider_calls, result.telemetry.total_tokens),
                         ('unit-deployment', 1, 250))
        self.assertEqual(parse.call_args.kwargs['model'], 'unit-deployment')

    def test_scenarios_use_the_azure_provider_and_send_the_rejected_text_back(self):
        for mode, status, calls in ((DraftModifier('wrong_accuracy', 1), 'RECOVERED', 2),
                                    (DraftModifier('invented_player', 2), 'DEGRADED_FALLBACK', 2)):
            sdk, parse = echoing_sdk()
            result = AzureRuntime(sdk, 'unit-deployment').run(episode(), modifier=mode)
            with self.subTest(status=status):
                self.assertEqual(result.telemetry.status, status)
                self.assertEqual(parse.call_count, calls)
                repair = json.loads(parse.call_args_list[1].kwargs['messages'][1]['content'])
                self.assertIn('rejected_draft', repair)

    def test_service_runs_azure_scenarios_without_calling_the_remote_api(self):
        sdk, _ = echoing_sdk()
        service = StudioService('https://example.invalid')
        with patch.dict('os.environ', ENVIRONMENT, clear=True), patch(
                'src.agents.azure_runtime.local_runtime', return_value=AzureRuntime(sdk, 'unit-deployment')), patch.object(
                service, '_request', side_effect=AssertionError('generation must stay in the studio')):
            result = service.broadcast(episode(), mode=DEMO_MODES[1], demo_error='wrong_duration')
        self.assertEqual(result.telemetry.generation_provider, 'AZURE_OPENAI')
        self.assertEqual(service.demo_review.scenario_status, 'COMPLETED')
        self.assertEqual(service.demo_review.attempts[0].provider, 'AZURE_OPENAI')

    def test_credential_failures_become_actionable_messages_without_upstream_text(self):
        response = httpx2.Response(401, request=httpx2.Request('POST', 'https://example.invalid'))
        error = AuthenticationError('secret upstream body', response=response, body=None)
        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=Mock(side_effect=error))))
        with patch.dict('os.environ', ENVIRONMENT, clear=True), patch(
                'src.agents.azure_runtime.local_runtime', return_value=AzureRuntime(sdk, 'unit-deployment')):
            with self.assertRaises(StudioServiceError) as failure:
                StudioService().broadcast(episode())
        self.assertNotIn('secret upstream body', str(failure.exception))
        self.assertIn('role assignment', str(failure.exception))

    def test_runtime_refuses_a_third_concurrent_request(self):
        runtime = AzureRuntime(echoing_sdk()[0], 'unit-deployment')
        self.assertTrue(runtime.slots.acquire(blocking=False) and runtime.slots.acquire(blocking=False))
        from src.agents.narrator import NarrativeGenerationError
        with self.assertRaises(NarrativeGenerationError):
            runtime.run(episode())


if __name__ == '__main__':
    unittest.main()
