"""Three-role orchestration with shared request state and bounded recovery."""
from copy import deepcopy
import re
from time import perf_counter
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from src.agents.narrator import (
    Language, LLMClient, MockLLMClient, NarrativeGenerationError,
    NarrativeOutput, NarrativeRequest, Persona, PersonaNarrator, SYSTEM_PROMPT, TONES,
)
from src.analytics.reconstruction import SyntheticReconstruction
from src.analytics.broadcast import BroadcastMetrics, FocusParticipation, compute_broadcast
from src.analytics.schemas import GoalEpisode, StrictModel, TacticalAnalysisResponse
from src.analytics.tactical_engine import TacticalEngine


class Handoff(StrictModel):
    from_agent: str
    to_agent: str
    attempt: int
    reason: str


class ExecutionTelemetry(StrictModel):
    handoffs: list[Handoff] = Field(default_factory=list)
    attempts: Annotated[int, Field(ge=0, le=2)] = 0
    critic_feedback: list[str] = Field(default_factory=list)
    latency_ms: Annotated[float, Field(ge=0)] = 0.0
    status: Literal['RUNNING', 'SUCCESS', 'RECOVERED', 'DEGRADED_FALLBACK'] = 'RUNNING'


class OrchestrationState(StrictModel):
    episode: GoalEpisode
    request: NarrativeRequest
    focus_player_id: str | None = None
    analysis: TacticalAnalysisResponse | None = None
    broadcast_metrics: BroadcastMetrics | None = None
    focus: FocusParticipation | None = None
    context: dict = Field(default_factory=dict)
    grounding: dict = Field(default_factory=dict)
    tactical_breakdown: str = ''
    proposal: dict | None = None
    generation_error: str | None = None
    narrative: NarrativeOutput | None = None
    telemetry: ExecutionTelemetry = Field(default_factory=ExecutionTelemetry)


class BroadcastResponse(StrictModel):
    episode: GoalEpisode
    analysis: TacticalAnalysisResponse
    narrative: NarrativeOutput
    broadcast_metrics: BroadcastMetrics
    focus: FocusParticipation
    telemetry: ExecutionTelemetry
    reconstruction: SyntheticReconstruction | None = None

    @model_validator(mode='after')
    def validate_reconstruction(self):
        if self.reconstruction is not None:
            self.reconstruction.validate_episode(self.episode)
        return self


class TacticalAnalystAgent:
    def run(self, state: OrchestrationState) -> None:
        state.analysis = TacticalEngine().analyze(state.episode)
        state.broadcast_metrics, state.focus = compute_broadcast(state.episode, state.focus_player_id)
        state.context, state.tactical_breakdown, state.grounding = PersonaNarrator().prepare(
            state.episode, state.analysis, **state.request.model_dump(),
        )
        state.context['focus'] = state.focus.model_dump()
        state.context['broadcast_metrics'] = state.broadcast_metrics.model_dump()


class PersonaNarratorAgent:
    def __init__(self, client: LLMClient):
        self.client = client

    def run(self, state: OrchestrationState) -> None:
        state.telemetry.attempts += 1
        state.proposal, state.generation_error = None, None
        context = deepcopy(state.context)
        context['critic_feedback'] = list(state.telemetry.critic_feedback)
        prompt = SYSTEM_PROMPT + '\nTone: ' + TONES[state.request.persona]
        prompt += '\nIf focus.participated is true, mention focus.player_name in commentary. Otherwise do not invent participation.'
        if state.telemetry.critic_feedback:
            prompt += '\nRepair the previous draft according to critic_feedback in the JSON context.'
        try:
            proposed = self.client.generate(system_prompt=prompt, context=context)
            state.proposal = proposed.model_dump()
        except (ValidationError, NarrativeGenerationError) as error:
            # SDK schema failures and explicit refusals are recoverable; bugs propagate.
            state.generation_error = str(error)


class GuardrailCriticAgent:
    def audit(self, state: OrchestrationState) -> bool:
        try:
            if state.generation_error:
                raise NarrativeGenerationError(state.generation_error)
            narrative = PersonaNarrator.validate(state.proposal, state.tactical_breakdown, state.grounding)
            if state.focus.participated:
                name = state.focus.player_name
                if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', narrative.commentary, re.IGNORECASE):
                    raise NarrativeGenerationError(f'Commentary must mention participating focus player: {name}')
            state.narrative = narrative
            return True
        except (ValidationError, NarrativeGenerationError) as error:
            state.telemetry.critic_feedback.append(str(error))
            return False

    def fallback(self, state: OrchestrationState) -> None:
        # Fixed short headline remains valid even with unusually long player names.
        names = list(dict.fromkeys(state.grounding['required_names'] + (
            [state.focus.player_name] if state.focus.participated else [])))
        commentary = ('Participantes verificados: ' if state.request.language == 'es'
                      else 'Verified participants: ') + '; '.join(names) + '.'
        state.proposal = dict(
            headline='Resumen verificado de la jugada' if state.request.language == 'es' else 'Verified goal sequence',
            commentary=commentary,
        )
        state.generation_error = None
        if not self.audit(state):
            raise ValueError('Deterministic fallback failed grounding; episode data requires correction')
        state.telemetry.status = 'DEGRADED_FALLBACK'


class BroadcastOrchestrator:
    def __init__(self, client: LLMClient | None = None):
        self.analyst = TacticalAnalystAgent()
        self.narrator = PersonaNarratorAgent(client if client is not None else MockLLMClient())
        self.critic = GuardrailCriticAgent()

    def run(self, episode: GoalEpisode, *, persona: Persona = 'TACTICAL_ANALYST',
            language: Language = 'en', focus_player_id: str | None = None,
            reconstruction: SyntheticReconstruction | None = None) -> BroadcastResponse:
        started = perf_counter()
        if reconstruction is not None:
            reconstruction.validate_episode(episode)
        state = OrchestrationState(
            episode=episode.model_copy(deep=True), request=NarrativeRequest(persona=persona, language=language),
            focus_player_id=focus_player_id,
        )
        self.analyst.run(state)
        state.telemetry.handoffs.append(Handoff(
            from_agent='TacticalAnalystAgent', to_agent='PersonaNarratorAgent', attempt=1,
            reason='Validated tactical facts, broadcast metrics and focus participation ready',
        ))
        for attempt in (1, 2):
            self.narrator.run(state)
            state.telemetry.handoffs.append(Handoff(
                from_agent='PersonaNarratorAgent', to_agent='GuardrailCriticAgent', attempt=attempt,
                reason='Audit generated proposal' if not state.generation_error else state.generation_error,
            ))
            if self.critic.audit(state):
                state.telemetry.status = 'SUCCESS' if attempt == 1 else 'RECOVERED'
                break
            if attempt == 1:
                state.telemetry.handoffs.append(Handoff(
                    from_agent='GuardrailCriticAgent', to_agent='PersonaNarratorAgent', attempt=2,
                    reason=state.telemetry.critic_feedback[-1],
                ))
            else:
                self.critic.fallback(state)
                state.telemetry.handoffs.append(Handoff(
                    from_agent='GuardrailCriticAgent', to_agent='DeterministicFallback', attempt=2,
                    reason='Second proposal rejected; validated deterministic narrative emitted',
                ))
        state.telemetry.latency_ms = (perf_counter() - started) * 1000
        return BroadcastResponse(
            episode=state.episode, analysis=state.analysis, narrative=state.narrative,
            broadcast_metrics=state.broadcast_metrics, focus=state.focus, telemetry=state.telemetry,
            reconstruction=reconstruction,
        )
