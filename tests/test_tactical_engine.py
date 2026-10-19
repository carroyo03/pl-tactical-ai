import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
from src.analytics.schemas import GoalEpisode
from src.analytics.tactical_engine import TacticalEngine
from src.ingest.repository import DuckDBRepository

SAMPLE = Path(__file__).resolve().parents[1] / 'data/raw/sample_goal_episode.json'


class TacticalTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(SAMPLE.read_text())
        self.engine = TacticalEngine()

    def analyze(self):
        return self.engine.analyze(GoalEpisode.model_validate(self.payload))

    def test_repository_to_engine(self):
        with DuckDBRepository() as repo:
            episode = repo.load_json(SAMPLE)
            self.assertEqual(repo.get(episode.goal_id), episode)
            self.assertEqual(self.engine.analyze(repo.get(episode.goal_id)).model_dump(), {
                'sequence_packing_score': 3,
                'tactical_pivot': 'P_10',
                'breakdown_zone': 'Middle Third',
                'tactical_cause': 'Quick transition after recovery',
            })
            repo.save(episode)
            self.assertEqual(repo.get(episode.goal_id), episode)
            with self.assertRaises(KeyError):
                repo.get("unknown' OR 1=1 --")

    def test_strict_endpoints_and_success(self):
        self.payload['events'] = [self.payload['events'][1]]
        event = self.payload['events'][0]
        event.update(start_x=50.0, end_x=65.0)
        self.assertEqual(self.analyze().sequence_packing_score, 1)
        for changes in ({'is_successful': False}, {'start_x': 65.0, 'end_x': 50.0},
                        {'start_x': 50.0, 'end_x': 50.0}, {'event_type': 'CARRY'}):
            with self.subTest(changes=changes):
                original = event.copy()
                event.update(changes)
                self.assertEqual(self.analyze().sequence_packing_score, 0)
                event.clear()
                event.update(original)

    def test_cause_priority_and_ten_second_boundary(self):
        first_time = self.payload['events'][0]['timestamp_sec']
        self.payload['timestamp_goal'] = first_time + 10
        self.assertEqual(self.analyze().tactical_cause, 'Quick transition after recovery')
        self.payload['timestamp_goal'] += 0.001
        self.assertEqual(self.analyze().tactical_cause, 'Central breakthrough through a vertical pass')
        self.payload['defenders_snapshot'] = []
        result = self.analyze()
        self.assertEqual(result.tactical_cause, 'Positional attack')
        self.assertIsNone(result.breakdown_zone)
        self.payload['events'] = [self.payload['events'][-1]]
        self.assertIsNone(self.analyze().tactical_pivot)

    def test_zone_boundaries_and_chronological_packing_tie(self):
        template = self.payload['events'][1]
        for x, zone in [(0.0, 'Defensive Third'), (33.299, 'Defensive Third'),
                        (33.3, 'Middle Third'), (66.599, 'Middle Third'),
                        (66.6, 'Attacking Third')]:
            with self.subTest(x=x):
                event = dict(template, start_x=x, end_x=100.0)
                self.payload['events'] = [event]
                self.payload['defenders_snapshot'] = [{'player_id': 'D', 'x': 90.0, 'y': 50.0}]
                self.assertEqual(self.analyze().breakdown_zone, zone)
        earlier = dict(template, event_id='early', start_x=10.0, end_x=100.0)
        later = dict(template, event_id='late', timestamp_sec=1425.0, start_x=70.0, end_x=100.0)
        self.payload['events'] = [later, earlier]
        self.assertEqual(self.analyze().breakdown_zone, 'Defensive Third')

    def test_centrality_tie_uses_first_seen(self):
        # Single directed edge: both centralities are zero. Player ID order disagrees.
        self.payload['events'] = self.payload['events'][2:]
        self.payload['events'][0]['player_id'] = 'Z'
        self.payload['events'][1]['player_id'] = 'A'
        self.payload['events'].reverse()
        self.assertEqual(self.analyze().tactical_pivot, 'Z')
        self.payload['events'][0]['team'] = 'AWAY'
        self.assertIsNone(self.analyze().tactical_pivot)

    def test_invalid_contracts(self):
        mutations = [
            lambda p: p.update(leadup_events=[]),
            lambda p: p.update(events=[]),
            lambda p: p['events'][0].update(is_successful='true'),
            lambda p: p['events'][0].update(start_x='35'),
            lambda p: p['events'][0].update(start_x=101.0),
            lambda p: p['events'][0].update(start_x=float('nan')),
            lambda p: p['events'][1].update(end_x=None),
            lambda p: p.update(timestamp_goal=0.0),
            lambda p: p['defenders_snapshot'].append(p['defenders_snapshot'][0]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                payload = copy.deepcopy(self.payload)
                mutate(payload)
                with self.assertRaises(ValidationError):
                    GoalEpisode.model_validate(payload)


if __name__ == '__main__':
    unittest.main()
