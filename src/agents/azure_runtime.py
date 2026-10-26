"""Azure OpenAI settings, SDK construction and a bounded studio runtime."""
from dataclasses import dataclass
import os
from threading import BoundedSemaphore, Lock
from time import perf_counter

from src.agents.narrator import AZURE_REQUEST_TIMEOUT_SEC, AzureOpenAIClient

DEFAULT_API_VERSION = '2024-10-21'
COGNITIVE_SERVICES_SCOPE = 'https://cognitiveservices.azure.com/.default'


@dataclass(frozen=True)
class AzureSettings:
    endpoint: str
    deployment: str
    api_key: str
    entra: bool
    api_version: str


def azure_settings() -> AzureSettings | None:
    """Read settings only when an endpoint, a deployment and one credential mode are present."""
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').strip()
    deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', '').strip()
    api_key = os.getenv('AZURE_OPENAI_API_KEY', '').strip()
    # Keyless Microsoft Entra ID sign-in is an explicit opt-in; an API key stays the default.
    entra = os.getenv('AZURE_OPENAI_AUTH', '').strip().lower() == 'entra'
    if not (endpoint and deployment and (api_key or entra)):
        return None
    return AzureSettings(endpoint, deployment, api_key, entra,
                         os.getenv('AZURE_OPENAI_API_VERSION', DEFAULT_API_VERSION))


def paid_models_disabled() -> bool:
    return os.getenv('DISABLE_PAID_MODELS', '').lower() == 'true'


def create_azure_sdk(settings: AzureSettings):
    """Return the SDK client and the close callbacks to run, in order, on shutdown."""
    from openai import AzureOpenAI

    closers, credentials = [], {'api_key': settings.api_key}
    if settings.entra and not settings.api_key:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        closers.append(credential.close)
        credentials = {'azure_ad_token_provider': get_bearer_token_provider(credential, COGNITIVE_SERVICES_SCOPE)}
    sdk = AzureOpenAI(azure_endpoint=settings.endpoint, **credentials, api_version=settings.api_version,
                      timeout=AZURE_REQUEST_TIMEOUT_SEC, max_retries=0)
    closers.append(sdk.close)
    return sdk, closers


def enabled() -> bool:
    """Studio-side Azure generation is an explicit opt-in: LLM_PROVIDER=azure plus full settings."""
    return (os.getenv('LLM_PROVIDER', '').lower() == 'azure' and not paid_models_disabled()
            and azure_settings() is not None)


class AzureRuntime:
    """Per-process bounded runner: two concurrent requests, two calls each, no result cache."""

    def __init__(self, sdk, deployment: str):
        self.sdk, self.deployment = sdk, deployment
        self.slots = BoundedSemaphore(2)

    @property
    def model(self) -> str:
        return self.deployment

    def run(self, episode, *, cancel_event=None, modifier=None, **selection):
        from src.agents.orchestrator import BroadcastOrchestrator
        from src.ingest.mock_generator import generate_mock_reconstruction
        from src.agents.narrator import NarrativeGenerationError
        if not self.slots.acquire(blocking=False):
            raise NarrativeGenerationError('The studio is busy right now. Please wait a moment and try again.')
        started = perf_counter()
        try:
            client = AzureOpenAIClient(self.sdk, self.deployment)
            result = BroadcastOrchestrator(client, modifier).run(
                episode, **selection, reconstruction=generate_mock_reconstruction(episode))
        finally:
            self.slots.release()
        telemetry = result.telemetry
        telemetry.model = self.deployment
        # Every narrator attempt is one provider request, including attempts that failed in transit.
        telemetry.provider_calls = telemetry.attempts
        telemetry.total_tokens = client.usage if client.usage_known else None
        telemetry.generation_latency_ms = (perf_counter() - started) * 1000
        return result

    def close(self, closers) -> None:
        for close in closers:
            close()


_lock = Lock()
_runtimes: dict = {}


def local_runtime() -> AzureRuntime:
    settings = azure_settings()
    if not enabled() or settings is None:
        raise ValueError('Azure OpenAI generation is not enabled')
    identity = (settings.endpoint, settings.deployment, settings.api_key, settings.entra, settings.api_version)
    with _lock:
        if identity not in _runtimes:
            if len(_runtimes) >= 3:
                raise ValueError('Restart the studio before changing Azure OpenAI settings again')
            sdk, _ = create_azure_sdk(settings)  # lives for the process; the OS reclaims it on exit
            _runtimes[identity] = AzureRuntime(sdk, settings.deployment)
        return _runtimes[identity]
