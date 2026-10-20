"""Linear goal intelligence API with lifespan-managed resources."""
from contextlib import ExitStack, asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from src.agents.narrator import (
    AzureOpenAIClient, Language, LLMClient, MockLLMClient,
    NarrativeOutput, Persona, PersonaNarrator,
)
from src.analytics.schemas import GoalEpisode, StrictModel, TacticalAnalysisResponse
from src.analytics.tactical_engine import TacticalEngine
from src.ingest.repository import DuckDBRepository
from src.ingest.mock_generator import generate_mock_episodes
from src.agents.orchestrator import BroadcastOrchestrator, BroadcastResponse

DEFAULT_SAMPLE_PATH = Path(__file__).resolve().parents[2] / 'data/raw/sample_goal_episode.json'
DEFAULT_API_VERSION = '2024-10-21'


class GoalIntelligenceResponse(StrictModel):
    episode: GoalEpisode
    analysis: TacticalAnalysisResponse
    narrative: NarrativeOutput


def create_app(
    *, client: LLMClient | None = None, sample_path: str | Path = DEFAULT_SAMPLE_PATH,
) -> FastAPI:
    """Injected clients are caller-owned; environment-created clients are app-owned."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as resources:
            repository = resources.enter_context(DuckDBRepository())
            if Path(sample_path).resolve() == DEFAULT_SAMPLE_PATH:
                # Seed from canonical fictional scenarios, never a stale local sample.
                for payload in generate_mock_episodes():
                    repository.save(GoalEpisode.model_validate(payload))
            else:
                repository.load_json(sample_path)
            selected_client = client
            if selected_client is None:
                endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').strip()
                api_key = os.getenv('AZURE_OPENAI_API_KEY', '').strip()
                deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', '').strip()
                if endpoint and api_key and deployment:
                    from openai import AzureOpenAI

                    sdk = AzureOpenAI(
                        azure_endpoint=endpoint, api_key=api_key,
                        api_version=os.getenv('AZURE_OPENAI_API_VERSION', DEFAULT_API_VERSION),
                        timeout=30.0, max_retries=0,
                    )
                    resources.callback(sdk.close)
                    selected_client = AzureOpenAIClient(sdk, deployment)
                else:
                    selected_client = MockLLMClient()
            app.state.repository = repository
            app.state.engine = TacticalEngine()
            app.state.narrator = PersonaNarrator(selected_client)
            app.state.orchestrator = BroadcastOrchestrator(selected_client)
            yield

    application = FastAPI(title='PL Tactical AI', lifespan=lifespan)

    @application.get('/goals', response_model=list[str])
    def list_goals(request: Request) -> list[str]:
        return request.app.state.repository.list_goal_ids()

    @application.get('/goals/{goal_id}/intelligence', response_model=GoalIntelligenceResponse)
    def goal_intelligence(
        goal_id: str, request: Request,
        persona: Persona = 'TACTICAL_ANALYST', language: Language = 'en',
    ) -> GoalIntelligenceResponse:
        try:
            episode = request.app.state.repository.get(goal_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Goal episode not found') from None
        analysis = request.app.state.engine.analyze(episode)
        narrative = request.app.state.narrator.narrate(
            episode, analysis, persona=persona, language=language,
        )
        return GoalIntelligenceResponse(episode=episode, analysis=analysis, narrative=narrative)

    @application.get('/goals/{goal_id}/broadcast', response_model=BroadcastResponse)
    def goal_broadcast(
        goal_id: str, request: Request,
        persona: Persona = 'TACTICAL_ANALYST', language: Language = 'en',
        focus_player_id: str | None = None,
    ) -> BroadcastResponse:
        try:
            episode = request.app.state.repository.get(goal_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Goal episode not found') from None
        return request.app.state.orchestrator.run(
            episode, persona=persona, language=language, focus_player_id=focus_player_id,
        )

    return application


app = create_app()
