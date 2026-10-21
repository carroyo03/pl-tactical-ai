"""Shared eligibility and static packing rules for scoring-team passes."""
from src.analytics.schemas import GoalEpisode, MatchEvent


def scoring_passes(episode: GoalEpisode) -> list[MatchEvent]:
    """Stable chronology, including failed attempts for the accuracy denominator."""
    return [event for event in sorted(episode.events, key=lambda event: event.timestamp_sec)
            if event.team == episode.scoring_team and event.event_type == 'PASS']


def bypassed_defender_ids(episode: GoalEpisode, event: MatchEvent) -> list[str]:
    """Strict X endpoints; no packing for failed, rival, backward or non-pass events."""
    if event.team != episode.scoring_team or event.event_type != 'PASS' or not event.is_successful:
        return []
    return [defender.player_id for defender in episode.defenders_snapshot
            if event.start_x < defender.x < event.end_x]
