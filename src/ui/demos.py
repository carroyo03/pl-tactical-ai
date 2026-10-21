"""Local narrative mistakes and review records for the studio demonstration."""
from dataclasses import dataclass

from src.agents.narrator import CreativeOutput, MockLLMClient
from src.analytics.schemas import GoalEpisode

DEMO_ERRORS = {
    'invented_player': 'A player who was not involved is mentioned',
    'wrong_recipient': 'A pass is attributed to the wrong receiver',
    'wrong_action': 'A recovery is attributed to the wrong player',
    'wrong_duration': 'The episode duration is reported incorrectly',
    'wrong_accuracy': 'The pass accuracy is reported incorrectly',
    'missing_names': 'The scorer and connector are left out',
}


@dataclass(frozen=True)
class RejectedDraft:
    headline: str
    commentary: str
    feedback: str


@dataclass(frozen=True)
class DemoReview:
    error: str
    evidence_explanation: str
    rejected_drafts: tuple[RejectedDraft, ...]


def _wrong_connection(events: list[dict]) -> tuple[str, str] | None:
    connections = {(event['player_name'], following['player_name'])
                   for event, following in zip(events, events[1:])
                   if event['event_type'] == 'PASS' and event['is_successful']
                   and event['team'] == following['team'] and event['player_id'] != following['player_id']}
    names = list(dict.fromkeys(event['player_name'] for event in events))
    for event in events:
        if event['event_type'] == 'PASS' and event['is_successful']:
            for recipient in names:
                pair = event['player_name'], recipient
                if pair[0] != pair[1] and pair not in connections:
                    return pair
    return None


def available_demo_errors(episode: GoalEpisode) -> list[str]:
    """Offer only mistakes that can be grounded in this episode."""
    events = [event.model_dump() for event in sorted(episode.events, key=lambda event: event.timestamp_sec)]
    recovered = {event['player_name'] for event in events
                 if event['event_type'] == 'RECOVERY' and event['is_successful']}
    return [kind for kind in DEMO_ERRORS
            if (kind != 'wrong_recipient' or _wrong_connection(events) is not None)
            and (kind != 'wrong_action' or any(event['player_name'] not in recovered for event in events))
            and (kind != 'wrong_accuracy' or any(event['event_type'] == 'PASS'
                                               and event['team'] == episode.scoring_team for event in events))]


def explain_critic_feedback(feedback: str) -> str:
    """Translate recognized validator feedback into a reader-facing sentence."""
    messages = [
        ('Named actor or recipient', 'The draft mentions a player who is not listed in this episode, so that involvement cannot be supported by the events.'),
        ('Pass recipient', 'The receiver named in the draft does not match the connection that can be inferred from the recorded event order.'),
        ('Player action', 'The action attributed to this player is not supported by their recorded events.'),
        ('Duration claim', 'The duration stated in the draft does not match the time between the first event and the goal.'),
        ('Percentage claim', 'The percentage stated in the draft does not match the scoring team’s completed and attempted passes.'),
        ('pass_accuracy claim', 'The stated pass accuracy does not match the scoring team’s recorded attempts.'),
        ('must mention the scorer or tactical pivot', 'Neither the scorer nor the selected connector is named, so the commentary is not adequately tied to this episode.'),
        ('participating focus player', 'The selected player takes part in this episode but is missing from the commentary.'),
        ('Internal IDs', 'An internal identifier appears in the draft where a player name or a natural explanation should be used.'),
        ('timed out', 'The provider did not respond within the configured time limit, so no complete draft could be accepted.'),
    ]
    for fragment, message in messages:
        if fragment.casefold() in feedback.casefold():
            return message
    return 'The draft did not satisfy a factual or output requirement. The recorded technical feedback is available below.'


class DemoLLMClient:
    """Inject one selected mistake once or twice, then return normal offline prose."""
    provider = 'OFFLINE_MOCK'

    def __init__(self, failures: int, error: str = 'invented_player'):
        if error not in DEMO_ERRORS:
            raise ValueError('Unknown demonstration error')
        self.failures, self.error, self.calls = failures, error, 0
        self.drafts: list[CreativeOutput] = []
        self.evidence_explanation = ''

    def generate(self, *, system_prompt: str, context: dict) -> CreativeOutput:
        self.calls += 1
        if self.calls > self.failures:
            return MockLLMClient().generate(system_prompt=system_prompt, context=context)
        spanish = context['language'] == 'es'
        anchor = context['scorer_name'] or context['pivot_name']
        base = f'{anchor} participa en la secuencia.' if spanish else f'{anchor} features in this sequence.'
        events = context['events']
        if self.error == 'invented_player':
            invented = 'Zorlan Phantom'
            suffix = 0
            while invented.casefold() in {event['player_name'].casefold() for event in events}:
                suffix += 1
                invented = f'Zorlan Phantom{suffix}'
            commentary = base + (f' {invented} regatea al portero.' if spanish else
                                  f' {invented} dribbles past the goalkeeper.')
            self.evidence_explanation = f'{invented} is absent from the player list and has no recorded actions. Only players present in the episode can be included in the explanation.'
        elif self.error == 'wrong_recipient':
            pair = _wrong_connection(events)
            if pair is None:
                raise ValueError('This episode cannot demonstrate an incorrect receiver')
            passer, recipient = pair
            commentary = base + (f' {passer} pasa a {recipient}.' if spanish else f' {passer} passes to {recipient}.')
            self.evidence_explanation = f'The recorded sequence does not support a pass from {passer} to {recipient}. Receivers are inferred from the immediately following event; intervening events cannot be skipped.'
        elif self.error == 'wrong_action':
            recovered = {event['player_name'] for event in events
                         if event['event_type'] == 'RECOVERY' and event['is_successful']}
            player = next(event['player_name'] for event in events if event['player_name'] not in recovered)
            commentary = base + (f' {player} recupera el balón.' if spanish else f' {player} wins possession.')
            self.evidence_explanation = f'No successful recovery is recorded for {player}. A recovery by another player cannot be attributed to them.'
        elif self.error == 'wrong_duration':
            duration = context['tactical_evidence']['duration_sec']
            wrong = int(duration) + 60
            commentary = base + (f' Duración de la jugada: {wrong} segundos.' if spanish else
                                  f' Sequence duration: {wrong} seconds.')
            self.evidence_explanation = f'The goal occurs {duration:g} seconds after the first event. The draft states {wrong} seconds, which does not match that replay clock.'
        elif self.error == 'wrong_accuracy':
            metrics = context['broadcast_metrics']
            accuracy = metrics['pass_accuracy']
            if accuracy is None:
                raise ValueError('This episode has no pass accuracy to contradict')
            wrong = 0 if accuracy >= 0.5 else 100
            commentary = base + (f' Precisión de pase: {wrong}%.' if spanish else f' Pass accuracy: {wrong}%.')
            self.evidence_explanation = (f'The scoring team completes {metrics["successful_passes"]} of '
                f'{metrics["total_passes"]} attempted passes, giving {accuracy * 100:g}% accuracy. '
                f'The draft reports {wrong}%, so the percentage must be corrected.')
        else:
            commentary = 'La secuencia termina en gol.' if spanish else 'The sequence ends in a goal.'
            self.evidence_explanation = f'The commentary must name the scorer or the selected connector. {anchor} is one of those verified participants, but neither role is named in this draft.'
        draft = CreativeOutput(headline='Borrador para revisar' if spanish else 'A draft for review', commentary=commentary)
        self.drafts.append(draft)
        return draft
