"""Offline HTTP integration and resource-lifecycle checks."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.agents.narrator import CreativeOutput, MockLLMClient
from src.api.app import create_app
from src.ingest.mock_generator import generate_mock_episodes


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        payload = generate_mock_episodes()[0]
        payload['goal_id'] = 'test-goal'
        cls.sample_path = Path(cls.directory.name) / 'episode.json'
        cls.sample_path.write_text(json.dumps(payload))
        # Explicit injection guarantees offline behavior even with Azure env vars set.
        cls.app = create_app(client=MockLLMClient(), sample_path=cls.sample_path)
        cls.http = cls.enterClassContext(TestClient(cls.app))

    def test_discover_and_analyze(self):
        discovery = self.http.get('/goals')
        self.assertEqual(discovery.status_code, 200)
        self.assertEqual(discovery.json(), ['test-goal'])
        response = self.http.get('/goals/test-goal/intelligence')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {'episode', 'analysis', 'narrative'})
        self.assertEqual(body['episode']['goal_id'], 'test-goal')
        self.assertEqual(len(body['episode']['events']), 4)
        self.assertEqual(len(body['episode']['defenders_snapshot']), 5)
        self.assertEqual(body['analysis']['sequence_packing_score'], 3)
        self.assertEqual(body['analysis']['tactical_pivot'], 'P_10')
        self.assertIn('Evan Rook', body['narrative']['tactical_breakdown'])
        self.assertIn('Milo Arden', body['narrative']['commentary'])
        self.assertNotIn('_grounding', body['narrative'])

    def test_spanish_and_persona(self):
        response = self.http.get('/goals/test-goal/intelligence', params={
            'persona': 'PASSIONATE_FAN', 'language': 'es',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('¡', response.json()['narrative']['commentary'])
        self.assertIn('tercio medio', response.json()['narrative']['tactical_breakdown'])

    def test_missing_goal(self):
        response = self.http.get('/goals/unknown/intelligence')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'detail': 'Goal episode not found'})

    def test_invalid_parameters(self):
        for params in ({'persona': 'UNKNOWN'}, {'language': 'fr'},
                       {'persona': ''}, {'language': ''}):
            with self.subTest(params=params):
                response = self.http.get('/goals/test-goal/intelligence', params=params)
                self.assertEqual(response.status_code, 422)

    def test_concurrent_reads(self):
        paths = ['/goals', '/goals/test-goal/intelligence'] * 8
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(self.http.get, paths))
        for path, response in zip(paths, responses):
            self.assertEqual(response.status_code, 200)
            if path == '/goals':
                self.assertEqual(response.json(), ['test-goal'])
            else:
                self.assertEqual(response.json()['analysis']['sequence_packing_score'], 3)

    def test_openapi_contract(self):
        schema = self.http.get('/openapi.json').json()
        response = schema['components']['schemas']['GoalIntelligenceResponse']
        self.assertEqual(set(response['required']), {'episode', 'analysis', 'narrative'})
        self.assertFalse(response['additionalProperties'])


class LifecycleTests(unittest.TestCase):
    def test_default_mock_and_repository_close(self):
        with patch.dict('os.environ', {}, clear=True):
            application = create_app()
            with TestClient(application) as http:
                self.assertIsInstance(application.state.narrator.client, MockLLMClient)
                self.assertEqual(http.get('/goals').status_code, 200)
                repository = application.state.repository
            with self.assertRaises(Exception) as failure:
                repository.list_goal_ids()
            self.assertIn('closed', str(failure.exception).lower())

    def test_environment_selects_azure_and_closes_owned_sdk(self):
        creative = CreativeOutput(headline='Milo Arden scores', commentary='Milo Arden features in this goal sequence.')
        message = SimpleNamespace(parsed=creative, refusal=None)
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason='stop')])
        environment = {
            'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com',
            'AZURE_OPENAI_API_KEY': 'test-only-key',
            'AZURE_OPENAI_DEPLOYMENT': 'test-gpt4o',
            'AZURE_OPENAI_API_VERSION': '2024-10-21',
        }
        sdk_type = MagicMock()
        with patch.dict('os.environ', environment, clear=True), patch('openai.AzureOpenAI', sdk_type):
            sdk = sdk_type.return_value
            sdk.chat.completions.parse.return_value = completion
            with TestClient(create_app()) as http:
                goal_id = http.get('/goals').json()[0]
                response = http.get(f'/goals/{goal_id}/intelligence')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(sdk.chat.completions.parse.call_args.kwargs['model'], 'test-gpt4o')
                self.assertEqual(sdk_type.call_args.kwargs['max_retries'], 0)
                self.assertEqual(sdk_type.call_args.kwargs['timeout'], 10.0)
                broadcast = http.get(f'/goals/{goal_id}/broadcast').json()
                self.assertEqual(broadcast['telemetry']['narrative_provider'], 'AZURE_OPENAI')
            sdk.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
