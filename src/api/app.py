"""Linear goal intelligence API with lifespan-managed resources."""
from contextlib import ExitStack, asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from src.agents.narrator import (
    AZURE_REQUEST_TIMEOUT_SEC, AzureOpenAIClient, Language, LLMClient, MockLLMClient,
    NarrativeGenerationError, NarrativeOutput, Persona, PersonaNarrator,
)
from src.agents.azure_runtime import azure_settings, create_azure_sdk, paid_models_disabled
from src.analytics.schemas import GoalEpisode, StrictModel, TacticalAnalysisResponse
from src.analytics.tactical_engine import TacticalEngine
from src.ingest.repository import DuckDBRepository
from src.ingest.mock_generator import generate_mock_episodes, generate_mock_reconstruction
from src.agents.orchestrator import BroadcastOrchestrator, BroadcastResponse
from src.api.security import APISecurityMiddleware, AdmissionControl, SecuritySettings, log_broadcast

DEFAULT_SAMPLE_PATH = Path(__file__).resolve().parents[2] / 'data/raw/sample_goal_episode.json'


class GoalIntelligenceResponse(StrictModel):
    episode: GoalEpisode
    analysis: TacticalAnalysisResponse
    narrative: NarrativeOutput


def create_app(
    *, client: LLMClient | None = None, sample_path: str | Path = DEFAULT_SAMPLE_PATH,
    security: SecuritySettings | None = None,
) -> FastAPI:
    """Injected clients are caller-owned; environment-created clients are app-owned."""
    settings = security if security is not None else SecuritySettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as resources:
            repository = resources.enter_context(DuckDBRepository())
            app.state.reconstructions = {}
            if Path(sample_path).resolve() == DEFAULT_SAMPLE_PATH:
                # Seed from canonical fictional scenarios, never a stale local sample.
                for payload in generate_mock_episodes():
                    episode = GoalEpisode.model_validate(payload)
                    repository.save(episode)
                    app.state.reconstructions[episode.goal_id] = generate_mock_reconstruction(episode)
            else:
                repository.load_json(sample_path)
            selected_client = client
            if selected_client is None:
                settings = azure_settings()
                if settings is not None and not paid_models_disabled():
                    sdk, closers = create_azure_sdk(settings)
                    for close in closers:
                        resources.callback(close)
                    selected_client = AzureOpenAIClient(sdk, settings.deployment)
                else:
                    selected_client = MockLLMClient()
            app.state.repository = repository
            app.state.engine = TacticalEngine()
            app.state.narrator = PersonaNarrator(selected_client)
            app.state.orchestrator = BroadcastOrchestrator(selected_client)
            yield

    application = FastAPI(title='PL Tactical AI', lifespan=lifespan,
                          docs_url=None if settings.service_token else '/docs',
                          redoc_url=None if settings.service_token else '/redoc',
                          openapi_url=None if settings.service_token else '/openapi.json')
    application.add_middleware(APISecurityMiddleware, control=AdmissionControl(settings))

    @application.get('/health', include_in_schema=False)
    def health():
        return {'status': 'ok'}

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
        try:
            narrative = request.app.state.narrator.narrate(
                episode, analysis, persona=persona, language=language,
            )
        except NarrativeGenerationError:
            raise HTTPException(status_code=503, detail='Narrative provider temporarily unavailable') from None
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
        result = request.app.state.orchestrator.run(
            episode, persona=persona, language=language, focus_player_id=focus_player_id,
            reconstruction=request.app.state.reconstructions.get(goal_id),
        )
        log_broadcast(settings, result)
        return result

    return application


app = create_app()
