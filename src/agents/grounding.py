"""Bounded deterministic checks for explicit claims, not general semantic proof."""
import re
import unicodedata


class GroundingError(ValueError):
    """Creative text contradicts or exceeds the supplied factual context."""


NUMBERS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
    'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'cero': 0, 'un': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
    'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10,
    'once': 11, 'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15,
    'dieciseis': 16, 'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19, 'veinte': 20,
}
NUMBER = r'(?:\d+(?:[.,]\d+)?|' + '|'.join(sorted(NUMBERS, key=len, reverse=True)) + ')'
DEFENDER = r'(?:defenders?|opponents?|defensor(?:es)?|rival(?:es)?)'
LINK = r'\s*(?:(?:is|was|of|at|es|fue|de|del|a)\s*|[:=]\s*)?'


def normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))


def number(value: str) -> float:
    return float(NUMBERS[value]) if value in NUMBERS else float(value.replace(',', '.'))


def matches_value(value: float, expected: float) -> bool:
    # Broadcast values may be printed at 0, 1, or 2 decimal places.
    return any(abs(value - round(expected, places)) < 1e-6 for places in (0, 1, 2, 6))


def audit_event_claims(text: str, facts: dict) -> None:
    """Check bounded actor/action patterns against recorded events, not general prose."""
    content = normalize(text)
    known = {normalize(name) for name in facts['known_names']}
    # Look for plausible multiword names in actor/recipient positions. This is
    # intentionally narrower than treating every capitalized phrase as a person.
    token = r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’\-]*"
    person = rf'{token}(?:\s+{token}){{1,3}}'
    action = (r'scores?|scored|shoots?|dribbles?|dribbled|carries|carried|passes|passed|'
              r'plays|played|wins|won|recovers|recovered|receives|received|finishes|finished|'
              r'features?|appears?|participates?|marca|marcó|anota|anotó|dispara|remata|'
              r'regatea|regateó|conduce|condujo|pasa|pasó|recupera|recuperó|recibe|aparece|participa')
    patterns = [rf'(?<!\w)({person})\s+(?i:{action})\b',
                rf'\b(?i:from|to|by|de|por|a|and|y)\s+({person})(?!\w)']
    generic = {'the team', 'el equipo', 'the goal', 'el gol', 'the move', 'la jugada',
               'defensive third', 'middle third', 'attacking third',
               'the defensive third', 'the middle third', 'the attacking third',
               'tercio defensivo', 'tercio medio', 'tercio ofensivo'}
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = normalize(match.group(1))
            if name not in known:
                name = re.sub(r'^(?:and|then|after|as|while|when|once|with|following|y|despues|tras|cuando|mientras|con|luego)\s+', '', name)
            name = re.sub(r"(?:'s|’s)$", '', name)
            if name not in known and name not in generic:
                raise GroundingError('Named actor or recipient is not present in the episode')

    events = facts.get('events', [])
    if not events:
        return
    by_name = {}
    for event in events:
        by_name.setdefault(normalize(event['player_name']), []).append(event)
    predicates = [
        (r'(?:dribbles|dribbled|carries|carried|regatea|regateo|conduce|condujo)\b', 'CARRY', False),
        (r'(?:shoots|shot|takes\s+a\s+shot|dispara|remata)\b', 'SHOT', False),
        (r'(?:wins\s+possession|won\s+possession|recovers\s+the\s+ball|recovered\s+the\s+ball|recupera\s+el\s+balon|recupero\s+el\s+balon)\b', 'RECOVERY', True),
        (r'(?:completes|completed|completa|completo)\s+(?:(?:a|the|his|un|el|su)\s+)?(?:pass|pase)\b', 'PASS', True),
        (r'(?:passes|passed|pasa|paso)\s+(?:to|a)\b', 'PASS', True),
    ]
    for name, recorded in by_name.items():
        player = re.escape(name)
        for predicate, kind, successful in predicates:
            if re.search(rf'(?<!\w){player}\s+(?:(?:then|immediately|next|subsequently|luego|despues|seguidamente)\s+){{0,2}}{predicate}', content):
                if not any(event['event_type'] == kind and (not successful or event['is_successful'])
                           for event in recorded):
                    raise GroundingError(f'Player action is not supported by recorded {kind} events')
        for match in re.finditer(rf'(?<!\w){player}\s+(?:completed|completes|completo|completa)\s+'
                                 rf'({NUMBER})\s+(?:of|out of|de)\s+({NUMBER})\s+(?:passes|pases)\b', content):
            attempts = [event for event in recorded if event['event_type'] == 'PASS']
            completed = sum(event['is_successful'] for event in attempts)
            if (number(match.group(1)), number(match.group(2))) != (completed, len(attempts)):
                raise GroundingError('Player pass completion count does not match their recorded attempts')

    connections = set()
    for event, following in zip(events, events[1:]):
        if (event['event_type'] == 'PASS' and event['is_successful']
                and following['team'] == event['team'] and following['player_id'] != event['player_id']):
            connections.add((normalize(event['player_name']), normalize(following['player_name'])))
    alternatives = '|'.join(re.escape(name) for name in sorted(by_name, key=len, reverse=True))
    for match in re.finditer(rf'(?<!\w)({alternatives})\s+(?:passes|passed|pasa|paso)\s+'
                             rf'(?:to|a)\s+({alternatives})(?!\w)', content):
        if (match.group(1), match.group(2)) not in connections:
            raise GroundingError('Pass recipient is not supported by the event sequence')

    # The canonical input has no evidence for keeper-beating moves or flight speeds.
    if re.search(r'\b(?:dribbles?\s+past\s+the\s+goalkeeper|regatea\s+al\s+portero|'
                 r'ball\s+speed|shot\s+speed|velocidad\s+del\s+balon|velocidad\s+del\s+disparo)\b', content):
        raise GroundingError('Goalkeeper-beating action or ball speed is not established by episode events')


def audit_tactical_claims(text: str, facts: dict) -> None:
    """Audit recognized counts, metric labels, zones and roles in English/Spanish.

    Paraphrases and arbitrary nonnumeric claims still need evaluation. This audit
    deliberately does not claim to prove every sentence true.
    """
    audit_event_claims(text, facts)
    content = normalize(text)
    packing = facts['analysis']['sequence_packing_score']
    patterns = [
        rf'\b({NUMBER})\s+(?:(?:opposing|bypassed|static|rivales|contrarios)\s+)?{DEFENDER}\b',
        rf'\bpacking(?:\s+(?:score|maximum|maximo|per|por|pass|pase)){{0,4}}{LINK}({NUMBER})\b',
        rf'\b{DEFENDER}\s+(?:bypassed|superados){LINK}({NUMBER})\b',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            if number(match.group(1)) != packing:
                raise GroundingError(f'Packing claim contradicts engine: expected {packing}, got {match.group(1)}')

    metrics = facts.get('broadcast_metrics', {})
    for match in re.finditer(rf'(?<!\w)({NUMBER})\s*%', content):
        accuracy = metrics.get('pass_accuracy')
        if accuracy is None or not matches_value(number(match.group(1)), accuracy * 100):
            raise GroundingError('Percentage claim does not match episode pass accuracy')
    for match in re.finditer(rf'\b(?:sequence duration|episode duration|duracion de la jugada|duracion de la secuencia){LINK}({NUMBER})', content):
        duration = facts.get('duration_sec')
        if duration is None or not matches_value(number(match.group(1)), duration):
            raise GroundingError('Duration claim does not match the episode clock')
    for match in re.finditer(rf'\b(?:completed|completes|completo|completa)\s+({NUMBER})\s+'
                             rf'(?:of|out of|de)\s+({NUMBER})\s+(?:passes|pases)\b', content):
        # Individual completion counts were checked against that player's events.
        prefix = content[:match.start()].rstrip()
        if any(re.search(rf'(?<!\w){re.escape(normalize(name))}$', prefix) for name in facts['known_names']):
            continue
        if (number(match.group(1)), number(match.group(2))) != (metrics.get('successful_passes'), metrics.get('total_passes')):
            raise GroundingError('Pass completion count does not match the scoring-team denominator')
    for label, key, multiplier in [
        (r'(?:pass accuracy|precision de pase|precision de pases)', 'pass_accuracy', 100),
        (r'(?:pass difficulty|dificultad del pase)', 'pass_difficulty', 1),
        (r'(?:pass distance|distancia del pase)', 'pass_distance_units', 1),
    ]:
        for match in re.finditer(rf'\b{label}{LINK}({NUMBER})', content):
            expected = metrics.get(key)
            if expected is None or not matches_value(number(match.group(1)), expected * multiplier):
                raise GroundingError(f'{key} claim does not match supplied broadcast facts')

    zones = [('Defensive Third', 'tercio defensivo'), ('Middle Third', 'tercio medio'),
             ('Attacking Third', 'tercio ofensivo')]
    for zone, spanish in zones:
        if any(normalize(label) in content for label in (zone, spanish)) and zone != facts['analysis']['breakdown_zone']:
            raise GroundingError('Breakdown zone contradicts engine')

    causes = [
        ('Quick transition after recovery', 'transicion rapida tras recuperacion'),
        ('Central breakthrough through a vertical pass', 'ruptura central por pase vertical'),
        ('Positional attack', 'ataque posicional'),
    ]
    for cause, spanish in causes:
        if any(normalize(label) in content for label in (cause, spanish)) and cause != facts['analysis']['tactical_cause']:
            raise GroundingError('Tactical cause contradicts engine')

    for name in facts['known_names']:
        player = re.escape(normalize(name))
        for expected, label in [
            (facts.get('pivot_name'), r'(?:tactical pivot|pivote tactico)'),
            (facts.get('scorer_name'), r'(?:scorer|goleador)'),
            (facts.get('key_pass_player_name'), r'(?:key.pass author|autor del pase clave)'),
        ]:
            if name != expected and (re.search(rf'\b{label}\s+(?:is|was|es|fue)\s+{player}(?!\w)', content)
                                     or re.search(rf'(?<!\w){player}\s+(?:is|was|es|fue)\s+(?:(?:the|el)\s+)?{label}\b', content)):
                raise GroundingError('Explicit player role contradicts episode facts')
        if name != facts.get('scorer_name') and re.search(
            rf'\b(?:goal\s+(?:is\s+|was\s+)?scored\s+by|gol\s+(?:es\s+|fue\s+)?marcado\s+por)\s+{player}(?!\w)', content,
        ):
            raise GroundingError('Passive goal-scoring claim names the wrong player')
        if name != facts.get('pivot_name') and re.search(
            rf'\b{player}\s+(?:is|was|es|fue)\s+(?:(?:the|el)\s+)?(?:tactical pivot|key connector|pivote tactico)\b', content,
        ):
            raise GroundingError('Tactical pivot claim names the wrong player')
        if name != facts.get('scorer_name') and re.search(
            rf'\b{player}\s+(?:scores|scored|marca|marco|anota|anoto)\b', content,
        ):
            raise GroundingError('Goal-scoring claim names the wrong player')
        key_passer = facts.get('key_pass_player_name')
        if key_passer and name != key_passer and re.search(
            rf'\b{player}\s+(?:plays|played|releases|released|juega|firma)\s+(?:the|el)\s+(?:key pass|pase clave)\b', content,
        ):
            raise GroundingError('Key-pass claim names the wrong player')

    if re.search(r'\b\d+(?:[.,]\d+)?\s*(?:meters?|metres?|metros?|m/s|km/h)\b', content):
        raise GroundingError('Physical distance or speed is not measured in this episode')

    allowed = [packing, *facts.get('allowed_numbers', [])]
    for key, value in metrics.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.append(value)
            if key == 'pass_accuracy':
                allowed.append(value * 100)
    # Names may legitimately contain digits; never change or reinterpret them.
    for name in facts['known_names']:
        content = re.sub(re.escape(normalize(name)), '', content)
    for match in re.finditer(r'(?<![\w])[+-]?\d+(?:[.,]\d+)?(?![\w])', content):
        value = number(match.group())
        if not any(matches_value(value, expected) for expected in allowed):
            raise GroundingError(f'Numeric claim is absent from supplied facts: {match.group()}')
