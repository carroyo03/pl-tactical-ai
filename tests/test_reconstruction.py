"""Synthetic event-time context stays separate from immutable packing evidence."""
from copy import deepcopy
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agents.narrator import MockLLMClient
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.reconstruction import SyntheticReconstruction
from src.analytics.schemas import GoalEpisode
from src.api.app import create_app
from src.ingest.mock_generator import generate_mock_episodes, generate_mock_reconstruction
from src.ui.service import parse_broadcast
from src.ui.visualization import build_pitch_figure


class ReconstructionTests(unittest.TestCase):
    def test_all_scenarios_have_reproducible_complete_event_frames(self):
        for payload in generate_mock_episodes():
            episode = GoalEpisode.model_validate(payload)
            reconstruction = generate_mock_reconstruction(episode)
            self.assertEqual(reconstruction, generate_mock_reconstruction(episode))
            reconstruction.validate_episode(episode)
            self.assertEqual(reconstruction.offside_assessment, 'NOT_ASSESSED')
            self.assertEqual(len(reconstruction.frames), len(episode.events))
            for event, frame in zip(episode.events, reconstruction.frames):
                self.assertEqual((frame.event_id, frame.timestamp_sec), (event.event_id, event.timestamp_sec))
                self.assertEqual(len(frame.opponents), 11)
                self.assertEqual(sum(p.role == 'GOALKEEPER' for p in frame.opponents), 1)
                actor = next(p for p in frame.attackers if p.player_id == event.player_id)
                self.assertEqual((actor.x, actor.y), (event.start_x, event.start_y))
            self.assertNotEqual(reconstruction.frames[0].opponents, reconstruction.frames[-1].opponents)

    def test_unknown_or_modified_episodes_do_not_get_fabricated_context(self):
        payload = generate_mock_episodes()[0]
        for modified in [dict(payload, goal_id='external'), dict(payload, timestamp_goal=1500.0)]:
            self.assertIsNone(generate_mock_reconstruction(GoalEpisode.model_validate(modified)))

    def test_invalid_frames_fail_strict_validation(self):
        episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        payload = generate_mock_reconstruction(episode).model_dump()
        missing_keeper = deepcopy(payload)
        missing_keeper['frames'][0]['opponents'].pop()
        with self.assertRaises(ValidationError):
            SyntheticReconstruction.model_validate(missing_keeper)
        for mutation in ('clock', 'coverage', 'actor', 'duplicates'):
            bad = deepcopy(payload)
            if mutation == 'clock':
                bad['frames'][0]['timestamp_sec'] += 1.0
            elif mutation == 'coverage':
                bad['frames'].pop()
            elif mutation == 'actor':
                bad['frames'][0]['attackers'][0]['x'] += 1.0
            else:
                bad['frames'][0]['opponents'][0]['player_id'] = bad['frames'][0]['opponents'][1]['player_id']
            with self.assertRaises((ValidationError, ValueError)):
                reconstruction = SyntheticReconstruction.model_validate(bad)
                reconstruction.validate_episode(episode)

    def test_replay_uses_reached_frame_without_changing_analysis(self):
        episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        orchestrator = BroadcastOrchestrator()
        legacy = orchestrator.run(episode)
        enriched = orchestrator.run(episode, focus_player_id='P_04',
                                    reconstruction=generate_mock_reconstruction(episode))
        self.assertEqual(legacy.analysis, enriched.analysis)
        self.assertEqual(legacy.broadcast_metrics.pass_difficulty, enriched.broadcast_metrics.pass_difficulty)
        self.assertEqual(len(episode.defenders_snapshot), 5)
        positions = []
        for offset, event_id in [(0.0, 'ev_01'), (3.49, 'ev_01'), (3.5, 'ev_02'), (6.0, 'ev_03'), (8.2, 'ev_04')]:
            figure = build_pitch_figure(enriched, offset)
            opponents = next(t for t in figure.data if t.meta.get('kind') == 'reconstructed_opponents')
            keeper = next(t for t in figure.data if t.meta.get('kind') == 'reconstructed_goalkeeper')
            attackers = next(t for t in figure.data if t.meta.get('kind') == 'reconstructed_attackers')
            self.assertEqual(opponents.meta['event_id'], event_id)
            self.assertEqual((len(opponents.x), len(keeper.x), len(attackers.x)), (10, 1, 3))
            self.assertTrue(attackers.meta['is_focus'])
            self.assertEqual(figure.data[0].visible, event_id == 'ev_02')
            positions.append(tuple(opponents.x))
        self.assertEqual(positions[0], positions[1])
        self.assertNotEqual(positions[1], positions[-1])
        old_payload = legacy.model_dump()
        old_payload.pop('reconstruction')
        self.assertIsNone(parse_broadcast(old_payload, persona='TACTICAL_ANALYST', language='en').reconstruction)

    def test_api_enriches_broadcast_but_preserves_legacy_episode(self):
        with TestClient(create_app(client=MockLLMClient())) as client:
            goal_id = client.get('/goals').json()[0]
            legacy = client.get(f'/goals/{goal_id}/intelligence').json()
            broadcast = client.get(f'/goals/{goal_id}/broadcast').json()
            self.assertEqual(set(legacy), {'episode', 'analysis', 'narrative'})
            self.assertNotIn('reconstruction', legacy['episode'])
            self.assertEqual(legacy['episode'], broadcast['episode'])
            self.assertEqual(broadcast['reconstruction']['version'], 'synthetic-reconstruction-v1')
            self.assertEqual(len(broadcast['reconstruction']['frames']), 4)


if __name__ == '__main__':
    unittest.main()
