"""Offline verification of service boundaries, capacity and minimal telemetry."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.agents.narrator import MockLLMClient
from src.api.app import create_app
from src.api.security import AdmissionControl, SecuritySettings
from src.ui.gateway import configuration_values
from src.ui.service import StudioService, StudioServiceError


class SecurityTests(unittest.TestCase):
    def setUp(self):
        provider = patch.dict('os.environ', {'LLM_PROVIDER': ''})
        provider.start()
        self.addCleanup(provider.stop)

    def test_service_boundary_and_readiness(self):
        token = 'test-only-service-token-with-sufficient-length'
        settings = SecuritySettings(service_token=token)
        with TestClient(create_app(client=MockLLMClient(), security=settings)) as http:
            self.assertEqual(http.get('/health').status_code, 200)
            self.assertEqual(http.get('/goals').status_code, 401)
            self.assertEqual(http.get('/goals', headers={'X-API-Service-Token': 'incorrect'}).status_code, 401)
            response = http.get('/goals', headers={'X-API-Service-Token': token})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(http.get('/openapi.json', headers={'X-API-Service-Token': token}).status_code, 404)

    def test_rate_limit_preserves_health_and_existing_response(self):
        settings = SecuritySettings(requests_per_minute=1)
        with TestClient(create_app(client=MockLLMClient(), security=settings)) as http:
            self.assertEqual(http.get('/goals').status_code, 200)
            response = http.get('/goals')
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response.headers)
            self.assertEqual(http.get('/health').status_code, 200)

    def test_capacity_recovers_and_rate_window_expires(self):
        now = [0.0]
        control = AdmissionControl(SecuritySettings(requests_per_minute=2, max_inflight=1), clock=lambda: now[0])
        self.assertIsNone(control.acquire())
        self.assertEqual(control.acquire(), 503)
        control.release()
        self.assertIsNone(control.acquire())
        control.release()
        self.assertEqual(control.acquire(), 429)
        now[0] = 61
        self.assertIsNone(control.acquire())
        control.release()

    def test_body_and_length_limits(self):
        with TestClient(create_app(client=MockLLMClient())) as http:
            self.assertEqual(http.request('GET', '/goals', content=b'not-used').status_code, 413)
            self.assertEqual(http.get('/goals', params={'extra': 'x' * 1100}).status_code, 414)

    def test_paid_models_can_be_disabled_even_with_credentials(self):
        environment = {'DISABLE_PAID_MODELS': 'true', 'AZURE_OPENAI_ENDPOINT': 'https://example.invalid',
                       'AZURE_OPENAI_API_KEY': 'test-only', 'AZURE_OPENAI_DEPLOYMENT': 'unused'}
        with patch.dict(os.environ, environment, clear=True), patch('openai.AzureOpenAI') as sdk:
            with TestClient(create_app()) as http:
                self.assertEqual(http.get('/goals/SYNTH_GOAL_01/broadcast').json()['telemetry']['narrative_provider'], 'OFFLINE_MOCK')
            sdk.assert_not_called()

    def test_summaries_are_bounded_and_payload_free(self):
        now = [0.0]
        control = AdmissionControl(SecuritySettings(structured_logs=True), clock=lambda: now[0])
        output = StringIO()
        with redirect_stdout(output):
            for _ in range(100):
                control.record(401, 1)
            self.assertEqual(output.getvalue(), '')
            now[0] = 61
            control.record(200, 2)
        record = json.loads(output.getvalue())
        self.assertEqual(record['counts']['401'], 100)
        self.assertEqual(set(record), {'event', 'window_sec', 'counts', 'total_duration_ms'})

    def test_studio_sends_service_credential_only_as_header(self):
        with patch.dict(os.environ, {'API_SERVICE_TOKEN': 'test-only-header-value'}):
            with patch('src.ui.service.urlopen', return_value=StringIO('[]')) as request:
                self.assertEqual(StudioService('https://api.example').list_goal_ids(), [])
        sent = request.call_args.args[0]
        self.assertEqual(sent.get_header('X-api-service-token'), 'test-only-header-value')
        self.assertNotIn('test-only-header-value', sent.full_url)

    def test_invalid_configuration_fails_closed(self):
        with patch.dict(os.environ, {'REQUIRE_API_SERVICE_TOKEN': 'true'}, clear=True):
            with self.assertRaises(ValueError):
                SecuritySettings.from_env()
        with patch.dict(os.environ, {'STUDIO_REQUEST_RATE': 'invalid'}, clear=True):
            with self.assertRaises(ValueError):
                configuration_values()

    def test_studio_capacity_is_shared_between_sessions(self):
        with patch.dict(os.environ, {'STUDIO_REQUESTS_PER_MINUTE': '1'}, clear=True):
            first = StudioService()
            episode = first.get_episode(first.list_goal_ids()[0])
            self.assertEqual(first.broadcast(episode).telemetry.status, 'SUCCESS')
            with self.assertRaises(StudioServiceError):
                StudioService().broadcast(episode, mode='Simulate 1 Critic Retry')


if __name__ == '__main__':
    unittest.main()
