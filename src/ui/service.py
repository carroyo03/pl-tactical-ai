"""Studio data access and clearly labelled, deterministic recovery demonstrations."""
import json
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from pydantic import ValidationError

from src.agents.narrator import MockLLMClient, NarrativeGenerationError, PersonaNarrator
from src.agents.orchestrator import BroadcastOrchestrator, BroadcastResponse
from src.analytics.broadcast import BroadcastMetrics
from src.analytics.schemas import GoalEpisode, TacticalAnalysisResponse
from src.ingest.mock_generator import generate_mock_episodes, generate_mock_reconstruction
from src.ingest.repository import DuckDBRepository
from src.ui.demos import AttemptReview, DemoReview, DraftModifier, RejectedDraft, available_demo_errors
from src.api.security import AdmissionControl, SecuritySettings

DemoMode = Literal['Normal', 'Simulate 1 Critic Retry', 'Simulate Double Failure -> Fallback']
DEMO_MODES = ['Normal', 'Simulate 1 Critic Retry', 'Simulate Double Failure -> Fallback']


def active_provider() -> str | None:
    """Studio-side hosted provider selected explicitly by LLM_PROVIDER, if any."""
    from src.agents import azure_runtime, groq_client
    if groq_client.enabled():
        return 'GROQ'
    if azure_runtime.enabled():
        return 'AZURE_OPENAI'
    return None


def active_model() -> str | None:
    provider = active_provider()
    if provider == 'GROQ':
        from src.agents.groq_client import DEFAULT_MODEL
        return os.getenv('GROQ_MODEL', DEFAULT_MODEL)
    if provider == 'AZURE_OPENAI':
        return os.getenv('AZURE_OPENAI_DEPLOYMENT', '').strip() or None
    return None


class StudioServiceError(ValueError):
    """Actionable data-source failure safe to display in the studio."""


@lru_cache(maxsize=4)
def _studio_admission(limit, inflight):
    return AdmissionControl(SecuritySettings(requests_per_minute=limit, max_inflight=inflight))


@contextmanager
def studio_capacity():
    limit = int(os.getenv('STUDIO_REQUESTS_PER_MINUTE', '0'))
    if not limit:
        yield
        return
    control = _studio_admission(limit, int(os.getenv('STUDIO_MAX_INFLIGHT', '2')))
    if control.acquire():
        raise StudioServiceError('The studio is busy right now. Please wait a moment and try again.')
    try:
        yield
    finally:
        control.release()


def parse_broadcast(payload: dict, *, persona: str, language: str) -> BroadcastResponse:
    """Restore grounding when JSON crosses HTTP; private Pydantic context is not serialized."""
    episode = GoalEpisode.model_validate(payload['episode'])
    analysis = TacticalAnalysisResponse.model_validate(payload['analysis'])
    metrics = BroadcastMetrics.model_validate(payload['broadcast_metrics'])
    _, _, grounding = PersonaNarrator().prepare(
        episode, analysis, persona=persona, language=language, broadcast_metrics=metrics,
    )
    return BroadcastResponse.model_validate(payload, context=grounding)


class StudioService:
    def __init__(self, api_base_url: str | None = None):
        self.api_base_url = api_base_url.rstrip('/') if api_base_url else None
        self.demo_review: DemoReview | None = None

    def _request(self, path: str) -> object:
        try:
            headers = {}
            if token := os.getenv('API_SERVICE_TOKEN'):
                headers['X-API-Service-Token'] = token
            request = Request(self.api_base_url + path, headers=headers)
            with urlopen(request, timeout=35) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code in (429, 503):
                raise StudioServiceError('The studio is busy right now. Please wait a moment and try again.') from error
            raise StudioServiceError(f'API returned HTTP {error.code}. Check the selected episode and API configuration.') from error
        except (URLError, TimeoutError, OSError) as error:
            raise StudioServiceError('Cannot reach the API. Start the backend or unset API_BASE_URL for local mode.') from error
        except (ValueError, UnicodeError) as error:
            raise StudioServiceError('API returned invalid JSON. Check the backend response.') from error

    def list_goal_ids(self) -> list[str]:
        if self.api_base_url:
            result = self._request('/goals')
            if not isinstance(result, list) or not all(isinstance(value, str) for value in result):
                raise StudioServiceError('API goal discovery must return a list of strings.')
            return result
        return [payload['goal_id'] for payload in generate_mock_episodes()]

    def get_episode(self, goal_id: str) -> GoalEpisode:
        if self.api_base_url:
            payload = self._request(f'/goals/{quote(goal_id, safe="")}/intelligence')
            try:
                return GoalEpisode.model_validate(payload['episode'])
            except (KeyError, TypeError, ValidationError) as error:
                raise StudioServiceError('API returned an invalid episode contract.') from error
        with DuckDBRepository() as repository:
            for payload in generate_mock_episodes():
                repository.save(GoalEpisode.model_validate(payload))
            return repository.get(goal_id)

    def broadcast(self, episode: GoalEpisode, *, persona='TACTICAL_ANALYST', language='en',
                  focus_player_id: str | None = None, mode: DemoMode = 'Normal',
                  demo_error: str = 'invented_player', cancel_event=None) -> BroadcastResponse:
        with studio_capacity():
            return self._broadcast(episode, persona=persona, language=language,
                                   focus_player_id=focus_player_id, mode=mode, demo_error=demo_error, cancel_event=cancel_event)

    def _broadcast(self, episode: GoalEpisode, *, persona, language, focus_player_id, mode,
                   demo_error, cancel_event=None) -> BroadcastResponse:
        self.demo_review = None
        if mode not in DEMO_MODES:
            raise ValueError('Unknown demo mode')
        if mode != 'Normal' and demo_error not in available_demo_errors(episode):
            raise ValueError('This demonstration error is not available for the episode')
        provider = active_provider()
        # A hosted provider runs inside this process. When it is enabled explicitly (LLM_PROVIDER),
        # episodes may still come from a remote API, but generation never goes through that API.
        if self.api_base_url and mode == 'Normal' and provider is None:
            params = dict(persona=persona, language=language)
            if focus_player_id is not None:
                params['focus_player_id'] = focus_player_id
            payload = self._request(f'/goals/{quote(episode.goal_id, safe="")}/broadcast?{urlencode(params)}')
            try:
                return parse_broadcast(payload, persona=persona, language=language)
            except (KeyError, TypeError, ValidationError) as error:
                raise StudioServiceError('API returned an invalid broadcast contract.') from error
        modifier = None if mode == 'Normal' else DraftModifier(demo_error, 1 if mode == DEMO_MODES[1] else 2)
        # Scenarios are never sent to a remote API: they use the hosted provider here, else the offline mock.
        if provider is not None:
            if provider == 'GROQ':
                from src.agents.groq_client import local_runtime
            else:
                from src.agents.azure_runtime import local_runtime
            try:
                runtime = local_runtime()
            except ValueError as error:
                raise StudioServiceError('AI commentary is not configured. Please check the local model settings.') from error
            try:
                result = runtime.run(episode, persona=persona, language=language, focus_player_id=focus_player_id,
                                     cancel_event=cancel_event, modifier=modifier)
            except NarrativeGenerationError as error:
                raise StudioServiceError(str(error)) from error
            except Exception as error:
                # Configuration failures (credentials, role, deployment) must be actionable, never raw.
                from azure.core.exceptions import ClientAuthenticationError
                from openai import APIStatusError
                if isinstance(error, (APIStatusError, ClientAuthenticationError)):
                    raise StudioServiceError('The model service rejected the request. Check the credentials, '
                                             'role assignment and deployment name.') from error
                raise
        else:
            result = BroadcastOrchestrator(MockLLMClient(), modifier).run(
                episode, persona=persona, language=language, focus_player_id=focus_player_id,
                reconstruction=generate_mock_reconstruction(episode),
            )
        if modifier is not None:
            self.demo_review = build_review(modifier, result, demo_error)
        return result


def build_review(modifier: DraftModifier, result: BroadcastResponse, error: str) -> DemoReview:
    """Join the modifier's records with the critic's verdicts, one entry per attempt."""
    telemetry = result.telemetry
    feedback = telemetry.critic_feedback
    attempts, rejected = [], []
    for record in modifier.records:
        rejected_here = record.attempt <= len(feedback)
        shown = record.altered if record.applied else record.original
        verdict = feedback[record.attempt - 1] if rejected_here else None
        attempts.append(AttemptReview(
            attempt=record.attempt, provider=telemetry.generation_provider, model=telemetry.model,
            targeted=record.targeted, modification_applied=record.applied, note=record.note,
            original_headline=record.original[0] if record.original else None,
            original_commentary=record.original[1] if record.original else None,
            audited_headline=shown[0] if shown else None, audited_commentary=shown[1] if shown else None,
            accepted=not rejected_here and shown is not None, feedback=verdict,
        ))
        if shown is not None and verdict is not None:
            rejected.append(RejectedDraft(shown[0], shown[1], verdict))
    altered = [a for a in attempts if a.modification_applied]
    status, note = 'COMPLETED', ''
    if any(a.accepted for a in altered):
        status, note = 'NOT_DETECTED', 'An altered draft was accepted by the critic, so the selected error was not detected.'
    elif len(altered) < modifier.limit:
        missing = next((a for a in attempts if a.targeted and not a.modification_applied), None)
        status = 'NOT_EXECUTED'
        note = (('The provider did not return a usable draft: ' + missing.note) if missing and missing.original_commentary is None
                else missing.note if missing else 'Fewer drafts than the scenario requires were available.')
    elif modifier.limit == 1 and altered[0].attempt == 2:
        note = 'The first provider draft was unavailable, so no correction attempt remained after the altered draft.'
    first = next((record for record in modifier.records if record.applied), None)
    return DemoReview(
        error=error, evidence_explanation=first.evidence_explanation if first else '',
        rejected_drafts=tuple(rejected), attempts=tuple(attempts), scenario_status=status, scenario_note=note,
    )
