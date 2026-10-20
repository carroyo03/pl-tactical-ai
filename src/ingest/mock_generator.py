"""Reproducible fictional goal episodes; no real teams, players or match data."""
import json
from pathlib import Path

from src.analytics.schemas import GoalEpisode
from src.analytics.reconstruction import SyntheticReconstruction


def generate_mock_episodes() -> list[dict]:
    episodes = []
    scenarios = [
        ('RECOVERY', [0.0, 3.5, 6.0, 8.2], [35.0, 35.0, 72.0, 88.0],
         ['Nolan Vale', 'Nolan Vale', 'Evan Rook', 'Milo Arden']),
        ('CARRY', [0.0, 6.0, 13.0, 20.0], [30.0, 35.0, 72.0, 88.0],
         ['Tarin Voss', 'Tarin Voss', 'Lior Fenwick', 'Oren Calder']),
        ('CARRY', [0.0, 8.0, 17.0, 28.0], [70.0, 72.0, 82.0, 90.0],
         ['Soren Wren', 'Soren Wren', 'Ilan Marlow', 'Darian Holt']),
    ]
    for number, (first_kind, offsets, origins, names) in enumerate(scenarios, 1):
        match_id = f'MATCH_SYNTHETIC_{number:02}'
        base = 1420.0
        destinations = [origins[1], origins[2], origins[3], 100.0]
        events = []
        for index, (kind, player, name, offset, start, end) in enumerate(zip(
            [first_kind, 'PASS', 'PASS', 'SHOT'], ['P_04', 'P_04', 'P_10', 'P_09'],
            names, offsets, origins, destinations,
        ), 1):
            events.append(dict(
                event_id=f'ev_{index:02}', match_id=match_id,
                timestamp_sec=base + offset, period=2, team='HOME',
                player_id=player, player_name=name, event_type=kind,
                start_x=start, start_y=[48.0, 48.0, 55.0, 45.0][index-1],
                end_x=end, end_y=[48.0, 55.0, 45.0, 50.0][index-1], is_successful=True,
            ))
        episodes.append(dict(
            goal_id=f'SYNTH_GOAL_{number:02}', match_id=match_id,
            timestamp_goal=events[-1]['timestamp_sec'], scoring_team='HOME', conceding_team='AWAY',
            events=events, defenders_snapshot=[
                dict(player_id=f'DEF_{i:02}', x=x, y=y)
                for i, (x, y) in enumerate([(50.0, 40.0), (52.0, 60.0), (65.0, 50.0),
                                             (78.0, 45.0), (80.0, 55.0)], 1)
            ],
        ))
    return episodes


def generate_mock_goal_episode(output_dir: str | Path = 'data/raw') -> list[dict]:
    """Write the compatible first episode plus two additional scenarios."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    episodes = generate_mock_episodes()
    for name, episode in zip(
        ['sample_goal_episode.json', 'episode_02.json', 'episode_03.json'], episodes,
    ):
        (directory / name).write_text(json.dumps(episode, indent=2) + '\n', encoding='utf-8')
        reconstruction = generate_mock_reconstruction(GoalEpisode.model_validate(episode))
        (directory / name.replace('.json', '_reconstruction.json')).write_text(
            reconstruction.model_dump_json(indent=2) + '\n', encoding='utf-8',
        )
    return episodes



def generate_mock_reconstruction(episode: GoalEpisode) -> SyntheticReconstruction | None:
    """Author visual context only for an exact canonical synthetic episode.

    Positions are event-time illustrations, not interpolated tracking. The next
    shooting/passing actor starts behind the authored deep defender at release.
    Units remain normalized; no offside decision or physical speed is inferred.
    """
    from src.analytics.reconstruction import (
        ReconstructionFrame, ReconstructionPosition, SyntheticReconstruction,
    )

    canonical = next((p for p in generate_mock_episodes() if p['goal_id'] == episode.goal_id), None)
    if canonical is None or GoalEpisode.model_validate(canonical) != episode:
        return None
    events = sorted(episode.events, key=lambda e: e.timestamp_sec)
    participants = list(dict.fromkeys(e.player_id for e in events))
    frames = []
    for index, event in enumerate(events):
        # Authored deep cover makes each scenario visually plausible at pass release.
        deep_x = min(96.0, max(84.0, (event.end_x or event.start_x) + 4.0))
        xs = [max(10.0, min(deep_x - 8.0, event.start_x + offset))
              for offset in (-18.0, -10.0, -4.0, 6.0, 12.0, 18.0, 24.0, 30.0)]
        xs += [deep_x - 4.0, deep_x]
        ys = [18.0, 36.0, 67.0, 27.0, 76.0, 45.0, 60.0, 86.0, 38.0, 63.0]
        opponents = [ReconstructionPosition(player_id=f'DEF_{i:02}', x=x, y=y)
                     for i, (x, y) in enumerate(zip(xs, ys), 1)]
        opponents.append(ReconstructionPosition(player_id='DEF_GK', x=98.0, y=50.0, role='GOALKEEPER'))
        attackers = []
        for player_id in participants:
            future = next((e for e in events[index:] if e.player_id == player_id), None)
            previous = next(e for e in reversed(events[:index + 1]) if e.player_id == player_id) if future is None else None
            target = future or previous
            if player_id == event.player_id:
                x, y = event.start_x, event.start_y
            else:
                x = max(0.0, min(deep_x - 3.0, target.start_x - 2.0 if future else target.start_x + 3.0))
                y = target.start_y
            attackers.append(ReconstructionPosition(player_id=player_id, x=x, y=y))
        frames.append(ReconstructionFrame(event_id=event.event_id, timestamp_sec=event.timestamp_sec,
                                          opponents=opponents, attackers=attackers))
    result = SyntheticReconstruction(frames=frames)
    result.validate_episode(episode)
    return result


if __name__ == '__main__':
    generate_mock_goal_episode()
    print('Generated three fictional episodes and their reconstructions in data/raw')
