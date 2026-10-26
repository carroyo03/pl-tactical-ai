"""Credential-independent provider, recovery and shared-cache coverage."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from threading import Event

import httpx2
from openai import APIStatusError, APIResponseValidationError

from src.agents.groq_client import GroqClient, GroqRuntime, MODELS, Transport, enabled
from src.agents.narrator import MockLLMClient, CreativeOutput, NarrativeRequest
from src.agents.orchestrator import OrchestrationState, TacticalAnalystAgent
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes


class FakeTransport:
    def __init__(self, failures=(), *, invalid=False):
        self.failures = list(failures)
        self.calls = []
        self.invalid = invalid

    def call(self, arguments, timeout, cancel_event=None):
        self.calls.append((arguments, timeout))
        if self.failures:
            raise self.failures.pop(0)
        context = json.loads(arguments['messages'][1]['content'])
        output = CreativeOutput.model_validate(context['verified_reference'])
        text = '{invalid' if self.invalid else output.model_dump_json()
        return NS(usage=NS(total_tokens=321), choices=[NS(finish_reason='stop',
                  message=NS(content=text, refusal=None))])


class GroqTests(unittest.TestCase):
    def setUp(self):
        self.episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        state = OrchestrationState(episode=self.episode, request=NarrativeRequest())
        TacticalAnalystAgent().run(state)
        self.context = state.context

    def runtime(self, transport=None, **kwargs):
        return GroqRuntime('unused', MODELS[0], transport=transport or FakeTransport(), **kwargs)

    def test_key_alone_does_not_enable_inference(self):
        with patch.dict('os.environ', {'LLM_PROVIDER': '', 'GROQ_API_KEY': 'secret'}):
            self.assertFalse(enabled())
        with patch.dict('os.environ', {'LLM_PROVIDER': 'groq', 'DISABLE_PAID_MODELS': 'true'}):
            self.assertFalse(enabled())

    def test_accepts_structured_response_and_reuses_isolated_copy(self):
        runtime = self.runtime()
        first = runtime.run(self.episode)
        second = runtime.run(self.episode)
        self.assertEqual(first.telemetry.narrative_provider, 'GROQ')
        self.assertFalse(first.telemetry.cache_hit)
        self.assertTrue(second.telemetry.cache_hit)
        self.assertEqual(len(runtime.transport.calls), 1)
        self.assertTrue(runtime.transport.calls[0][0]['response_format']['json_schema']['strict'])
        second.telemetry.status = 'DEGRADED_FALLBACK'
        self.assertEqual(runtime.run(self.episode).telemetry.status, 'SUCCESS')

    def test_equivalent_parallel_requests_are_coalesced(self):
        runtime = self.runtime()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: runtime.run(self.episode), range(2)))
        self.assertEqual(len(runtime.transport.calls), 1)
        self.assertEqual(sum(r.telemetry.cache_hit for r in results), 1)

    def test_cache_expiration_selection_and_capacity(self):
        runtime = self.runtime(ttl=0, max_entries=1)
        runtime.run(self.episode)
        runtime.run(self.episode)
        self.assertEqual(len(runtime.transport.calls), 2)
        runtime.ttl = 900
        runtime.run(self.episode, language='es')
        self.assertEqual(len(runtime.cache), 1)

    def test_timeout_recovers_once_and_reports_usage(self):
        runtime = self.runtime(FakeTransport([TimeoutError()]))
        result = runtime.run(self.episode)
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        self.assertEqual(result.telemetry.provider_calls, 2)
        self.assertEqual(result.telemetry.total_tokens, 321)

    def test_malformed_provider_response_can_recover(self):
        response = httpx2.Response(200, request=httpx2.Request('POST', 'https://example.test'))
        runtime = self.runtime(FakeTransport([APIResponseValidationError(response, body={})]))
        result = runtime.run(self.episode)
        self.assertEqual(result.telemetry.status, 'RECOVERED')
        self.assertEqual(len(runtime.transport.calls), 2)

    def test_retry_after_outside_deadline_uses_fallback(self):
        response = httpx2.Response(503, headers={'retry-after': '60'},
                                  request=httpx2.Request('POST', 'https://example.test'))
        runtime = self.runtime(FakeTransport([APIStatusError('unavailable', response=response, body=None)]))
        with self.assertLogs('src.agents.groq_client', level='WARNING'):
            result = runtime.run(self.episode)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(len(runtime.transport.calls), 1)

    def test_observed_token_limit_stops_further_requests(self):
        runtime = self.runtime()
        runtime.record_tokens(7000)
        result = runtime.run(self.episode)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertFalse(runtime.transport.calls)

    def test_invalid_outputs_exhaust_budget_and_use_rich_fallback(self):
        runtime = self.runtime(FakeTransport(invalid=True))
        result = runtime.run(self.episode, language='es')
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertEqual(len(runtime.transport.calls), 2)
        self.assertGreater(len(result.narrative.commentary.split()), 20)
        self.assertFalse(runtime.cache)

    def test_configuration_error_does_not_retry_or_leak_body(self):
        response = httpx2.Response(401, request=httpx2.Request('POST', 'https://example.test'))
        error = APIStatusError('SECRET UPSTREAM RESPONSE', response=response, body=None)
        runtime = self.runtime(FakeTransport([error]))
        with self.assertLogs('src.agents.groq_client', level='WARNING') as logs:
            result = runtime.run(self.episode)
        self.assertEqual(len(runtime.transport.calls), 1)
        self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_FALLBACK')
        self.assertNotIn('SECRET', str(logs.output) + result.model_dump_json())

    def test_fallback_matrix_preserves_language_persona_and_focus(self):
        for raw in generate_mock_episodes():
            episode = GoalEpisode.model_validate(raw)
            for language in ('en', 'es'):
                for persona in ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER'):
                    for focus in (episode.events[0].player_id, 'P_99'):
                        with self.subTest(goal=episode.goal_id, language=language, persona=persona, focus=focus):
                            runtime = self.runtime()
                            runtime.cooldown(60)
                            result = runtime.run(episode, language=language, persona=persona,
                                                 focus_player_id=focus)
                            self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
                            self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_FALLBACK')
                            self.assertEqual(result.focus.participated, focus != 'P_99')
                            self.assertFalse(runtime.transport.calls)
                            self.assertIsNotNone(result.reconstruction)

    def test_rate_limit_enters_cooldown_without_second_network_call(self):
        response = httpx2.Response(429, headers={'retry-after': '60'},
                                  request=httpx2.Request('POST', 'https://example.test'))
        error = APIStatusError('quota', response=response, body=None)
        runtime = self.runtime(FakeTransport([error]))
        result = runtime.run(self.episode)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        runtime.run(self.episode, language='es')
        self.assertEqual(len(runtime.transport.calls), 1)

    def test_deadline_and_capacity_skip_network(self):
        runtime = self.runtime()
        client = GroqClient(runtime, 0)
        with self.assertRaisesRegex(ValueError, 'generation_deadline'):
            client.generate(system_prompt='', context=self.context)
        runtime.slots.acquire()
        runtime.slots.acquire()
        try:
            result = runtime.run(self.episode)
            self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
            self.assertFalse(runtime.transport.calls)
        finally:
            runtime.slots.release()
            runtime.slots.release()

    def test_expired_deadline_prevents_second_network_call(self):
        runtime = self.runtime(FakeTransport([TimeoutError()]))
        # The second generate observes expiration rather than starting a new call.
        client = GroqClient(runtime, float('inf'))
        with self.assertRaises(ValueError):
            client.generate(system_prompt='', context=self.context)
        client.deadline = 0
        with self.assertRaises(ValueError):
            client.generate(system_prompt='', context=self.context)
        self.assertEqual(len(runtime.transport.calls), 1)

    def test_transport_cancels_request_at_total_deadline(self):
        transport = Transport('unused')
        cancelled = []
        async def slow(**kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
        try:
            with patch.object(transport.client.chat.completions, 'create', side_effect=slow):
                with self.assertRaises(TimeoutError):
                    transport.call({}, .05)
                # Flush the loop before checking coroutine cleanup.
                asyncio.run_coroutine_threadsafe(asyncio.sleep(.01), transport.loop).result(1)
                self.assertTrue(cancelled)
        finally:
            transport.close()

    def test_caller_cancellation_prevents_network_and_retry(self):
        runtime = self.runtime()
        cancel = Event()
        cancel.set()
        result = runtime.run(self.episode, cancel_event=cancel)
        self.assertEqual(result.telemetry.status, 'DEGRADED_FALLBACK')
        self.assertFalse(runtime.transport.calls)
        self.assertEqual(result.telemetry.attempts, 1)

    def test_unexpected_programming_error_is_not_hidden_as_fallback(self):
        runtime = self.runtime(FakeTransport([RuntimeError('Internal bug')]))
        with self.assertRaisesRegex(RuntimeError, 'Internal bug'):
            runtime.run(self.episode)
        self.assertFalse(runtime.cache)
