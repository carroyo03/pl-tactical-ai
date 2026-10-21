"""Bounded API admission and payload-free operational summaries."""
from collections import Counter, deque
from dataclasses import dataclass, field
from hmac import compare_digest
import json
import os
from threading import Lock
from time import monotonic

from starlette.responses import JSONResponse


@dataclass(frozen=True)
class SecuritySettings:
    service_token: str = field(default='', repr=False)
    requests_per_minute: int = 120
    max_inflight: int = 4
    structured_logs: bool = False

    def __post_init__(self):
        if not 1 <= self.requests_per_minute <= 10000 or not 1 <= self.max_inflight <= 32:
            raise ValueError('Invalid API capacity configuration')
        if self.service_token and len(self.service_token) < 32:
            raise ValueError('API service token must contain at least 32 characters')

    @classmethod
    def from_env(cls):
        token = os.getenv('API_SERVICE_TOKEN', '')
        if os.getenv('REQUIRE_API_SERVICE_TOKEN', '').lower() == 'true' and not token:
            raise ValueError('An API service token is required by this deployment')
        return cls(
            service_token=token,
            requests_per_minute=int(os.getenv('API_REQUESTS_PER_MINUTE', '120')),
            max_inflight=int(os.getenv('API_MAX_INFLIGHT', '4')),
            structured_logs=os.getenv('STRUCTURED_LOGS', '').lower() == 'true',
        )


class AdmissionControl:
    """One-process limits; deliberately independent of client-supplied addresses."""

    def __init__(self, settings, clock=monotonic):
        self.settings, self.clock = settings, clock
        self._lock = Lock()
        self._arrivals = deque()
        self._inflight = 0
        self._counts = Counter()
        self._last_summary = clock()
        self._latency_ms = 0.0

    def acquire(self):
        with self._lock:
            now = self.clock()
            while self._arrivals and self._arrivals[0] <= now - 60:
                self._arrivals.popleft()
            if len(self._arrivals) >= self.settings.requests_per_minute:
                return 429
            if self._inflight >= self.settings.max_inflight:
                return 503
            self._arrivals.append(now)
            self._inflight += 1
            return None

    def release(self):
        with self._lock:
            self._inflight -= 1

    def record(self, status, elapsed_ms):
        with self._lock:
            self._counts[f'{status // 100}xx'] += 1
            if status in (401, 429, 503):
                self._counts[str(status)] += 1
            self._latency_ms += elapsed_ms
            now = self.clock()
            if self.settings.structured_logs and now - self._last_summary >= 60:
                print(json.dumps({
                    'event': 'api_window', 'window_sec': round(now - self._last_summary, 1),
                    'counts': dict(self._counts), 'total_duration_ms': round(self._latency_ms, 2),
                }), flush=True)
                self._counts.clear()
                self._latency_ms = 0.0
                self._last_summary = now


class APISecurityMiddleware:
    def __init__(self, app, control):
        self.app, self.control = app, control

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = self.control.clock()
        status = 500
        acquired = False
        headers = dict(scope.get('headers', []))

        async def protected_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = list(message.get('headers', [])) + [
                    (b'x-content-type-options', b'nosniff'),
                    (b'cache-control', b'no-store'),
                ]
            await send(message)

        async def reject(code, detail):
            response = JSONResponse({'detail': detail}, status_code=code,
                                    headers={'Retry-After': '60'} if code in (429, 503) else {})
            await response(scope, receive, protected_send)

        try:
            if scope['path'] == '/health':
                return await self.app(scope, receive, protected_send)
            if len(scope.get('raw_path', b'')) > 512 or len(scope.get('query_string', b'')) > 1024:
                return await reject(414, 'Request is too long')
            if headers.get(b'transfer-encoding') or headers.get(b'content-length', b'0') != b'0':
                return await reject(413, 'Request bodies are not supported')
            token = self.control.settings.service_token
            supplied = headers.get(b'x-api-service-token', b'')
            if token and not compare_digest(supplied, token.encode()):
                return await reject(401, 'Service authentication is required')
            capacity_status = self.control.acquire()
            if capacity_status:
                return await reject(capacity_status, 'The service is busy. Please try again shortly.')
            acquired = True
            await self.app(scope, receive, protected_send)
        finally:
            if acquired:
                self.control.release()
            if scope['path'] != '/health':
                self.control.record(status, (self.control.clock() - started) * 1000)


def log_broadcast(settings, result):
    """Emit only bounded, typed execution facts, never generated text or inputs."""
    if settings.structured_logs:
        telemetry = result.telemetry
        print(json.dumps({
            'event': 'broadcast_complete', 'status': telemetry.status,
            'attempts': telemetry.attempts, 'provider': telemetry.narrative_provider,
            'latency_ms': round(telemetry.latency_ms, 2),
        }), flush=True)
