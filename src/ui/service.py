"""Studio data access and clearly labelled, deterministic recovery demonstrations."""
import json
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from pydantic import ValidationError

from src.agents.narrator import CreativeOutput, MockLLMClient, PersonaNarrator
from src.agents.orchestrator import BroadcastOrchestrator, BroadcastResponse
from src.analytics.schemas import GoalEpisode, TacticalAnalysisResponse
from src.ingest.mock_generator import generate_mock_episodes
from src.ingest.repository import DuckDBRepository

DemoMode = Literal['Normal', 'Simulate 1 Critic Retry', 'Simulate Double Failure -> Fallback']
DEMO_MODES = ['Normal', 'Simulate 1 Critic Retry', 'Simulate Double Failure -> Fallback']


class StudioServiceError(ValueError):
    """Actionable data-source failure safe to display in the studio."""


class DemoLLMClient:
    """New instance per run: fail once or twice, then use the offline client."""
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def generate(self, *, system_prompt: str, context: dict) -> CreativeOutput:
        self.calls += 1
        if self.calls <= self.failures:
            return CreativeOutput(headline='Draft awaiting audit', commentary='A draft without required player names.')
        return MockLLMClient().generate(system_prompt=system_prompt, context=context)


def parse_broadcast(payload: dict, *, persona: str, language: str) -> BroadcastResponse:
    """Restore grounding when JSON crosses HTTP; private Pydantic context is not serialized."""
    episode = GoalEpisode.model_validate(payload['episode'])
    analysis = TacticalAnalysisResponse.model_validate(payload['analysis'])
    _, _, grounding = PersonaNarrator().prepare(episode, analysis, persona=persona, language=language)
    return BroadcastResponse.model_validate(payload, context=grounding)


class StudioService:
    def __init__(self, api_base_url: str | None = None):
        self.api_base_url = api_base_url.rstrip('/') if api_base_url else None

    def _request(self, path: str) -> object:
        try:
            with urlopen(self.api_base_url + path, timeout=35) as response:
                return json.load(response)
        except HTTPError as error:
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
                  focus_player_id: str | None = None, mode: DemoMode = 'Normal') -> BroadcastResponse:
        if mode not in DEMO_MODES:
            raise ValueError('Unknown demo mode')
        if self.api_base_url and mode == 'Normal':
            params = dict(persona=persona, language=language)
            if focus_player_id is not None:
                params['focus_player_id'] = focus_player_id
            payload = self._request(f'/goals/{quote(episode.goal_id, safe="")}/broadcast?{urlencode(params)}')
            try:
                return parse_broadcast(payload, persona=persona, language=language)
            except (KeyError, TypeError, ValidationError) as error:
                raise StudioServiceError('API returned an invalid broadcast contract.') from error
        client = MockLLMClient() if mode == 'Normal' else DemoLLMClient(1 if mode == DEMO_MODES[1] else 2)
        return BroadcastOrchestrator(client).run(
            episode, persona=persona, language=language, focus_player_id=focus_player_id,
        )
