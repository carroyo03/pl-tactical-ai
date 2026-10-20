"""SDK failures are injected locally: no credentials, requests or sleeps."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx2
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from src.agents.narrator import AzureOpenAIClient, CreativeOutput
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.api.app import create_app
from src.ingest.mock_generator import generate_mock_episodes


def sdk_client(outputs):
    parse = Mock(side_effect=outputs)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
    return AzureOpenAIClient(sdk, 'test-deployment'), parse


def completion():
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason='stop', message=SimpleNamespace(refusal=None, parsed=CreativeOutput(
            headline='The goal explained', commentary='Milo Arden finishes the move.',
        )),
    )])


def status_error(code):
    response = httpx2.Response(code, request=httpx2.Request('POST', 'https://example.invalid'))
    error_type = RateLimitError if code == 429 else AuthenticationError if code == 401 else APIStatusError
    return error_type('Sensitive upstream body must not reach narrative telemetry', response=response, body=None)


class ProviderFailureTests(unittest.TestCase):
    def setUp(self):
        self.episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        self.request = httpx2.Request('POST', 'https://example.invalid')

    def test_timeout_connection_rate_limit_and_server_errors_recover_once(self):
        for error in (APITimeoutError(self.request), APIConnectionError(request=self.request),
                      status_error(429), status_error(503), status_error(408)):
            with self.subTest(error=type(error).__name__):
                client, parse = sdk_client([error, completion()])
                result = BroadcastOrchestrator(client).run(self.episode)
                self.assertEqual(result.telemetry.status, 'RECOVERED')
                self.assertEqual(result.telemetry.attempts, 2)
                self.assertEqual(result.telemetry.generation_provider, 'AZURE_OPENAI')
                self.assertEqual(result.telemetry.narrative_provider, 'AZURE_OPENAI')
                self.assertEqual(parse.call_count, 2)
                self.assertEqual(parse.call_args.kwargs['timeout'], 10.0)
                self.assertEqual(parse.call_args.kwargs['max_completion_tokens'], 600)
                self.assertNotIn('Sensitive upstream body', str(result.telemetry.critic_feedback))

    def test_exhausted_transport_failures_use_honest_offline_fallback(self):
        client, parse = sdk_client([APITimeoutError(self.request), status_error(429)])
        result = BroadcastOrchestrator(client).run(self.episode)
        self.assertEqual(parse.call_count, 2)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(result.telemetry.generation_provider, 'AZURE_OPENAI')
        self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_FALLBACK')
        self.assertEqual(len(result.telemetry.critic_feedback), 2)
        self.assertIn('timed out', result.telemetry.critic_feedback[0])
        self.assertIn('429', result.telemetry.critic_feedback[1])

    def test_configuration_and_programming_errors_are_not_hidden(self):
        for error in (status_error(401), RuntimeError('Implementation bug')):
            client, parse = sdk_client([error])
            with self.assertRaises(type(error)):
                BroadcastOrchestrator(client).run(self.episode)
            self.assertEqual(parse.call_count, 1)

    def test_legacy_endpoint_returns_clean_unavailability_error(self):
        client, _ = sdk_client([APITimeoutError(self.request)])
        with TestClient(create_app(client=client)) as http:
            response = http.get('/goals/SYNTH_GOAL_01/intelligence')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'detail': 'Narrative provider temporarily unavailable'})

    def test_mock_and_fallback_provider_labels_are_distinct(self):
        result = BroadcastOrchestrator().run(self.episode)
        self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_MOCK')
        self.assertEqual(result.telemetry.generation_provider, 'OFFLINE_MOCK')


if __name__ == '__main__':
    unittest.main()
