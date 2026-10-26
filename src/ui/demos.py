"""Local narrative mistakes and review records for the studio demonstration."""
from dataclasses import dataclass, field
import re

from pydantic import ValidationError

from src.agents.narrator import CreativeOutput
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
class AttemptReview:
    """Provenance of one generation attempt, from the provider draft to the critic's verdict."""
    attempt: int
    provider: str
    model: str | None
    targeted: bool
    modification_applied: bool
    note: str
    original_headline: str | None
    original_commentary: str | None
    audited_headline: str | None
    audited_commentary: str | None
    accepted: bool
    feedback: str | None


@dataclass(frozen=True)
class DemoReview:
    error: str
    evidence_explanation: str
    rejected_drafts: tuple[RejectedDraft, ...]
    attempts: tuple[AttemptReview, ...] = ()
    # COMPLETED: every targeted draft was altered and rejected by the critic.
    # NOT_DETECTED: an altered draft was accepted. NOT_EXECUTED: the intervention could not happen.
    scenario_status: str = 'COMPLETED'
    scenario_note: str = ''


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


@dataclass
class ModificationRecord:
    attempt: int
    targeted: bool
    applied: bool = False
    note: str = ''
    original: tuple[str, str] | None = None
    altered: tuple[str, str] | None = None
    evidence_explanation: str = ''


_DURATION_CLAIM = re.compile(
    r'(?i)((?:sequence duration|episode duration|duraci[oó]n de la (?:jugada|secuencia))'
    r'\s*(?:(?:is|was|of|at|es|fue|de|del|a)\s*|[:=]\s*)?)(\d+(?:[.,]\d+)?)')
_PERCENT = re.compile(r'\d+(?:[.,]\d+)?\s*%')


def _sentence_end(text: str) -> str:
    text = text.rstrip()
    return text if text[-1:] in '.!?' else text + '.'


def _alter(error: str, headline: str, commentary: str, context: dict, required_names: list[str]):
    """Return (headline, commentary, description, evidence explanation) or None if unreliable."""
    spanish = context['language'] == 'es'
    events = context['events']
    if error == 'invented_player':
        invented, suffix = 'Zorlan Phantom', 0
        while invented.casefold() in {event['player_name'].casefold() for event in events}:
            suffix += 1
            invented = f'Zorlan Phantom{suffix}'
        sentence = f'{invented} regatea al portero.' if spanish else f'{invented} dribbles past the goalkeeper.'
        return (headline, _sentence_end(commentary) + ' ' + sentence, f'Added a sentence about {invented}',
                f'{invented} is absent from the player list and has no recorded actions. Only players present in the episode can be included in the explanation.')
    if error == 'wrong_recipient':
        pair = _wrong_connection(events)
        if pair is None:
            return None
        passer, recipient = pair
        sentence = f'{passer} pasa a {recipient}.' if spanish else f'{passer} passes to {recipient}.'
        return (headline, _sentence_end(commentary) + ' ' + sentence, f'Added a pass from {passer} to {recipient}',
                f'The recorded sequence does not support a pass from {passer} to {recipient}. Receivers are inferred from the immediately following event; intervening events cannot be skipped.')
    if error == 'wrong_action':
        recovered = {event['player_name'] for event in events
                     if event['event_type'] == 'RECOVERY' and event['is_successful']}
        player = next((event['player_name'] for event in events if event['player_name'] not in recovered), None)
        if player is None:
            return None
        sentence = f'{player} recupera el balón.' if spanish else f'{player} wins possession.'
        return (headline, _sentence_end(commentary) + ' ' + sentence, f'Added a recovery attributed to {player}',
                f'No successful recovery is recorded for {player}. A recovery by another player cannot be attributed to them.')
    if error == 'wrong_duration':
        duration = context['tactical_evidence']['duration_sec']
        wrong = int(duration) + 60
        explanation = (f'The goal occurs {duration:g} seconds after the first event. '
                       f'The draft states {wrong} seconds, which does not match that replay clock.')
        if _DURATION_CLAIM.search(commentary):
            return (headline, _DURATION_CLAIM.sub(lambda m: m.group(1) + str(wrong), commentary, count=1),
                    f'Replaced the stated duration with {wrong} seconds', explanation)
        sentence = f'Duración de la jugada: {wrong} segundos.' if spanish else f'Sequence duration: {wrong} seconds.'
        return (headline, _sentence_end(commentary) + ' ' + sentence, f'Added a duration of {wrong} seconds', explanation)
    if error == 'wrong_accuracy':
        metrics = context['broadcast_metrics']
        accuracy = metrics['pass_accuracy']
        if accuracy is None:
            return None
        wrong = 0 if accuracy >= 0.5 else 100
        explanation = (f'The scoring team completes {metrics["successful_passes"]} of '
                       f'{metrics["total_passes"]} attempted passes, giving {accuracy * 100:g}% accuracy. '
                       f'The draft reports {wrong}%, so the percentage must be corrected.')
        if _PERCENT.search(commentary):
            return (headline, _PERCENT.sub(f'{wrong}%', commentary, count=1),
                    f'Replaced the stated percentage with {wrong}%', explanation)
        sentence = f'Precisión de pase: {wrong}%.' if spanish else f'Pass accuracy: {wrong}%.'
        return (headline, _sentence_end(commentary) + ' ' + sentence, f'Added a pass accuracy of {wrong}%', explanation)
    # missing_names: remove every mention of the scorer and the connector.
    names = sorted(required_names, key=len, reverse=True)
    if not names:
        return None
    stand_in = 'el atacante' if spanish else 'the attacker'
    altered = []
    for text in (headline, commentary):
        for name in names:
            text = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', stand_in, text, flags=re.IGNORECASE)
        altered.append(text)
    if (altered[1] == commentary
            or any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', altered[1], re.IGNORECASE) for name in names)):
        return None
    return (altered[0], altered[1], 'Replaced the scorer and connector names with a generic reference',
            f'The commentary must name the scorer or the selected connector. {" and ".join(names)} are the verified participants, but neither is named in this draft.')


class DraftModifier:
    """Alter a provider's first alterable drafts before review; facts and the critic stay untouched."""

    def __init__(self, error: str, drafts: int):
        if error not in DEMO_ERRORS:
            raise ValueError('Unknown demonstration error')
        if drafts not in (1, 2):
            raise ValueError('Between one and two drafts can be altered')
        self.error, self.limit = error, drafts
        self.records: list[ModificationRecord] = []

    def apply(self, attempt: int, proposal: dict, context: dict, required_names: list[str]) -> dict:
        altered = sum(record.applied for record in self.records)
        original = (proposal['headline'], proposal['commentary'])
        record = ModificationRecord(attempt, targeted=altered < self.limit, original=original)
        self.records.append(record)
        if not record.targeted:
            return proposal
        altered = _alter(self.error, *original, context, required_names)
        if altered is not None:
            try:
                CreativeOutput(headline=altered[0], commentary=altered[1])
            except ValidationError:
                altered = None
        if altered is None:
            record.note = 'The selected error could not be applied reliably to this draft, so it was left unchanged.'
            return proposal
        record.applied, record.altered = True, (altered[0], altered[1])
        record.note, record.evidence_explanation = altered[2], altered[3]
        return {**proposal, 'headline': altered[0], 'commentary': altered[1]}

    def record_unavailable(self, attempt: int, reason: str | None) -> None:
        self.records.append(ModificationRecord(
            attempt, targeted=sum(r.applied for r in self.records) < self.limit,
            note=reason or 'No draft was returned.'))
