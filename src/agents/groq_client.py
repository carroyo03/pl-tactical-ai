"""Opt-in local inference with bounded recovery and no public activation."""
import asyncio
import atexit
from collections import OrderedDict, deque
from concurrent.futures import TimeoutError as WaitTimeout
from hashlib import sha256
import json
import logging
import os
import re
from pathlib import Path
from threading import BoundedSemaphore, Lock, Thread
from time import monotonic, sleep

import httpx2 as httpx
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, APIResponseValidationError

from src.agents.narrator import CreativeOutput, NarrativeGenerationError, MockLLMClient
from src.agents.grounding import normalize
from src.agents.writing import writing_messages

LOG = logging.getLogger(__name__)
MODELS = ('openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'qwen/qwen3.8-27b')
DEFAULT_MODEL = 'openai/gpt-oss-120b'


def enabled():
    return (os.getenv('LLM_PROVIDER', '').lower() == 'groq'
            and os.getenv('DISABLE_PAID_MODELS', '').lower() != 'true')


class ProviderUnavailable(NarrativeGenerationError):
    def __init__(self, category, *, retryable=False):
        super().__init__(category)
        self.retryable = retryable


class Transport:
    """Own one async client and event loop; synchronous callers never own the loop."""
    def __init__(self, key):
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self.loop.run_forever, daemon=True, name='groq-network')
        self.thread.start()
        self.client = AsyncOpenAI(
            api_key=key, base_url='https://api.groq.com/openai/v1', max_retries=0,
            timeout=httpx.Timeout(10, connect=3, pool=1, write=3),
            http_client=httpx.AsyncClient(limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
                                         follow_redirects=False, trust_env=False),
        )
        atexit.register(self.close)

    def call(self, arguments, timeout, cancel_event=None):
        async def request():
            async with asyncio.timeout(timeout):
                return await self.client.chat.completions.create(**arguments)
        future = asyncio.run_coroutine_threadsafe(request(), self.loop)
        try:
            deadline = monotonic() + timeout
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ProviderUnavailable('generation_cancelled')
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                try:
                    return future.result(timeout=min(.1, remaining))
                except WaitTimeout:
                    if future.done():
                        return future.result()
        except BaseException:
            # Also cancel on caller interruption; a cancelled request is not refunded.
            future.cancel()
            raise

    def close(self):
        if self.loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop).result(timeout=3)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=3)
            if not self.thread.is_alive():
                self.loop.close()


class GroqClient:
    provider = 'GROQ'

    def __init__(self, runtime, deadline, cancel_event=None):
        self.runtime, self.deadline = runtime, deadline
        self.cancel_event = cancel_event
        self.calls = 0
        self.usage = 0
        self.usage_known = False
        self.next_retry_at = 0

    def generate(self, *, system_prompt, context):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise ProviderUnavailable('generation_cancelled')
        delay = self.next_retry_at - monotonic()
        if delay > 0:
            if monotonic() + delay >= self.deadline:
                raise ProviderUnavailable('generation_deadline')
            if self.cancel_event is not None:
                if self.cancel_event.wait(delay):
                    raise ProviderUnavailable('generation_cancelled')
            else:
                sleep(delay)
        remaining = self.deadline - monotonic()
        if remaining <= .1 or self.calls >= 2:
            raise ProviderUnavailable('generation_deadline')
        arguments = dict(
            model=self.runtime.model,
            messages=writing_messages(system_prompt, context),
            response_format={'type': 'json_schema', 'json_schema': {
                'name': 'commentary', 'strict': True, 'schema': CreativeOutput.model_json_schema()}},
            max_completion_tokens=2048,
            reasoning_effort='low',
        )
        # Bound input before spending quota. Conservative byte bound for these fixtures.
        if len(json.dumps(arguments).encode()) > 28000:
            raise ProviderUnavailable('input_limit')
        remaining = self.deadline - monotonic()
        if remaining <= .1:
            raise ProviderUnavailable('generation_deadline')
        if not self.runtime.admit():
            raise ProviderUnavailable('provider_cooldown')
        self.calls += 1
        self.next_retry_at = monotonic() + .25
        try:
            completion = self.runtime.transport.call(arguments, min(10.0, remaining),
                                                     cancel_event=self.cancel_event)
        except (TimeoutError, APITimeoutError):
            raise ProviderUnavailable('provider_timeout', retryable=True) from None
        except (APIResponseValidationError, json.JSONDecodeError):
            raise ProviderUnavailable('provider_invalid_output', retryable=True) from None
        except APIConnectionError:
            raise ProviderUnavailable('provider_connection', retryable=True) from None
        except APIStatusError as error:
            code = error.status_code
            if code == 429:
                try:
                    delay = float(error.response.headers.get('retry-after', '60'))
                except ValueError:
                    delay = 60
                self.runtime.cooldown(delay)
                raise ProviderUnavailable('provider_quota') from None
            try:
                delay = max(.25, float(error.response.headers.get('retry-after', '.25')))
            except ValueError:
                delay = .25
            self.next_retry_at = monotonic() + min(delay, 86400)
            category = 'provider_configuration' if code in (400, 401, 403, 404, 422) else 'provider_unavailable'
            LOG.warning('groq_failure category=%s status=%s', category, code)
            raise ProviderUnavailable(category, retryable=code in (408, 409) or code >= 500) from None
        if completion.usage:
            self.usage_known = True
            self.usage += completion.usage.total_tokens or 0
            self.runtime.record_tokens(completion.usage.total_tokens or 0)
        if not completion.choices:
            raise ProviderUnavailable('provider_empty', retryable=True)
        choice = completion.choices[0]
        if choice.finish_reason != 'stop' or getattr(choice.message, 'refusal', None):
            raise ProviderUnavailable('provider_incomplete', retryable=True)
        try:
            output = CreativeOutput.model_validate_json(choice.message.content or '')
            text = normalize(output.commentary)
            if context.get('language') == 'en' and re.search(r'instantanea defensiva|\b(?:recupera|remata|conduccion)\b', text):
                raise ValueError('Commentary must use the requested language only')
            if context.get('language') == 'es' and re.search(r'\b(?:snapshot|pitch_units)\b', text):
                raise ValueError('Commentary must use the requested language only')
            if not re.search(r'snapshot|static|instantanea|estatic', text):
                raise ValueError('Static comparison limitation must be explained')
            if context.get('pivot_name') and not re.search(r'infer|event order|orden de|suggest|sugier|deduc', text):
                raise ValueError('Passing connections must be described as inferred')
            if re.search(r'most frequent|most repeated|mas frecuente|mas repetid', text):
                raise ValueError('Defender count is not pass frequency')
            if re.search(r'\b(?:victory|victoria|wins the match|gana el partido)\b',
                         output.commentary + ' ' + output.headline, re.IGNORECASE):
                raise ValueError('Match outcome is not established by an episode')
            return output
        except ValueError:
            raise ProviderUnavailable('provider_invalid_output', retryable=True) from None


class GroqRuntime:
    """Per-process bounded cache, coalescing, quota guard and connection owner."""
    def __init__(self, key, model, *, transport=None, ttl=900, max_entries=128):
        if model not in MODELS:
            raise ValueError('Unsupported local evaluation model')
        self.model = model
        self.transport = transport if transport is not None else Transport(key)
        self.ttl, self.max_entries = ttl, max_entries
        self.lock = Lock()
        self.slots = BoundedSemaphore(2)
        self.key_locks = [Lock() for _ in range(32)]
        self.cache = OrderedDict()
        self.arrivals = deque()
        self.token_usage = deque()
        self.blocked_until = 0
        self.daily_calls = 0
        self.day_started = monotonic()

    def cooldown(self, delay):
        with self.lock:
            self.blocked_until = max(self.blocked_until, monotonic() + max(1, min(delay, 86400)))

    def record_tokens(self, count):
        with self.lock:
            self.token_usage.append((monotonic(), count))

    def admit(self):
        with self.lock:
            now = monotonic()
            if now - self.day_started >= 86400:
                self.day_started, self.daily_calls = now, 0
            while self.arrivals and self.arrivals[0] <= now - 60:
                self.arrivals.popleft()
            while self.token_usage and self.token_usage[0][0] <= now - 60:
                self.token_usage.popleft()
            # Observed usage is a conservative stop signal, not an exact tokenizer or
            # reservation system; provider limits and account settings remain authoritative.
            if (now < self.blocked_until or len(self.arrivals) >= 4 or self.daily_calls >= 100
                    or sum(count for _, count in self.token_usage) >= 6000):
                return False
            self.arrivals.append(now)
            self.daily_calls += 1
            return True

    def run(self, episode, *, cancel_event=None, modifier=None, **selection):
        from src.agents.orchestrator import BroadcastOrchestrator
        selection = {'persona': 'TACTICAL_ANALYST', 'language': 'en', 'focus_player_id': None, **selection}
        started = monotonic()
        deadline = started + 20
        revisions = b''.join(p.read_bytes() for directory in ('agents', 'analytics')
                             for p in sorted((Path(__file__).resolve().parents[1] / directory).glob('*.py')))
        key = sha256(episode.model_dump_json().encode() + json.dumps(selection, sort_keys=True).encode()
                     + self.model.encode() + sha256(revisions).digest()).hexdigest()
        gate = self.key_locks[int(key[:8], 16) % len(self.key_locks)]
        acquired = gate.acquire(timeout=max(0, deadline - monotonic()))
        try:
            if acquired and modifier is None:
                with self.lock:
                    now = monotonic()
                    for stale in [k for k, (expires, _) in self.cache.items() if expires <= now]:
                        del self.cache[stale]
                    if key in self.cache:
                        result = self.cache[key][1].model_copy(deep=True)
                        self.cache.move_to_end(key)
                        result.telemetry.cache_hit = True
                        result.telemetry.provider_calls = 0
                        result.telemetry.total_tokens = None
                        result.telemetry.latency_ms = (now - started) * 1000
                        return result
            admitted = acquired and self.slots.acquire(blocking=False)
            client = GroqClient(self, deadline if admitted else started, cancel_event)
            try:
                from src.ingest.mock_generator import generate_mock_reconstruction
                result = BroadcastOrchestrator(client, modifier).run(episode, **selection,
                                                          reconstruction=generate_mock_reconstruction(episode))
            finally:
                if admitted:
                    self.slots.release()
            result.telemetry.model = self.model
            result.telemetry.provider_calls = client.calls
            result.telemetry.total_tokens = client.usage if client.usage_known else None
            result.telemetry.generation_latency_ms = result.telemetry.latency_ms
            if result.telemetry.narrative_provider == 'GROQ' and modifier is None:
                with self.lock:
                    self.cache[key] = (monotonic() + self.ttl, result.model_copy(deep=True))
                    while len(self.cache) > self.max_entries:
                        self.cache.popitem(last=False)
            LOG.info('groq_complete model=%s status=%s calls=%s tokens=%s latency_ms=%.1f',
                     self.model, result.telemetry.status, client.calls, client.usage, result.telemetry.latency_ms)
            return result
        finally:
            if acquired:
                gate.release()


_runtime_lock = Lock()
_runtimes = {}


def local_runtime():
    if not enabled():
        raise ValueError('Local model generation is not enabled')
    key = os.getenv('GROQ_API_KEY', '').strip()
    model = os.getenv('GROQ_MODEL', DEFAULT_MODEL)
    if not key:
        raise ValueError('Local model credentials are missing')
    identity = (sha256(key.encode()).hexdigest(), model)
    with _runtime_lock:
        if identity not in _runtimes:
            if len(_runtimes) >= 3:
                raise ValueError('Restart the local studio before changing model credentials again')
            _runtimes[identity] = GroqRuntime(key, model)
        return _runtimes[identity]
