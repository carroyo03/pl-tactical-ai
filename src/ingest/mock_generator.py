"""Reproducible fictional goal episodes; no real teams, players or match data."""
import json
from pathlib import Path


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
    return episodes


if __name__ == '__main__':
    generate_mock_goal_episode()
    print('Generated three fictional episodes in data/raw')
