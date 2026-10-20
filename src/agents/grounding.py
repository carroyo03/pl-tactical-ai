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


def audit_tactical_claims(text: str, facts: dict) -> None:
    """Audit recognized counts, metric labels, zones and roles in English/Spanish.

    Paraphrases and arbitrary nonnumeric claims still need evaluation. This audit
    deliberately does not claim to prove every sentence true.
    """
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
