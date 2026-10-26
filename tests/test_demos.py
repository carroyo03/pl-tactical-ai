"""Local error demonstrations preserve real validation, facts and request isolation."""
import unittest
from unittest.mock import patch

from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes
from src.ui.demos import DEMO_ERRORS, available_demo_errors, explain_critic_feedback
from src.ui.service import DEMO_MODES, StudioService


class DemoTests(unittest.TestCase):
    def setUp(self):
        provider = patch.dict('os.environ', {'LLM_PROVIDER': ''})
        provider.start()
        self.addCleanup(provider.stop)

    def test_all_cases_recover_or_fallback_for_every_episode_and_language(self):
        service = StudioService()
        for payload in generate_mock_episodes():
            episode = GoalEpisode.model_validate(payload)
            baseline = service.broadcast(episode)
            self.assertIsNone(service.demo_review)
            self.assertEqual(set(available_demo_errors(episode)), set(DEMO_ERRORS))
            for language in ('en', 'es'):
                for error in DEMO_ERRORS:
                    for mode in DEMO_MODES[1:]:
                        with self.subTest(goal=episode.goal_id, language=language, error=error, mode=mode):
                            result = service.broadcast(episode, language=language, mode=mode, demo_error=error,
                                                       focus_player_id='P_04')
                            expected = 'RECOVERED' if mode == DEMO_MODES[1] else 'DEGRADED_FALLBACK'
                            rejected = 1 if mode == DEMO_MODES[1] else 2
                            self.assertEqual(result.telemetry.status, expected)
                            self.assertEqual(result.telemetry.attempts, 2)
                            self.assertEqual(result.analysis, baseline.analysis)
                            self.assertEqual(result.tactical_evidence, baseline.tactical_evidence)
                            self.assertEqual(result.broadcast_metrics.pass_accuracy, baseline.broadcast_metrics.pass_accuracy)
                            review = service.demo_review
                            self.assertEqual(review.error, error)
                            self.assertEqual(len(review.rejected_drafts), rejected)
                            self.assertTrue(review.evidence_explanation)
                            self.assertNotIn('Zorlan Phantom', result.narrative.commentary)
                            self.assertEqual([draft.feedback for draft in review.rejected_drafts], result.telemetry.critic_feedback)
                            for draft in review.rejected_drafts:
                                self.assertTrue(draft.headline)
                                self.assertTrue(draft.commentary)
                                self.assertNotIn('technical feedback is available', explain_critic_feedback(draft.feedback))

    def test_remote_configuration_never_receives_injected_mistakes(self):
        service = StudioService('https://example.invalid')
        episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        with patch.object(service, '_request', side_effect=AssertionError('No remote request is permitted')):
            for error in DEMO_ERRORS:
                result = service.broadcast(episode, mode=DEMO_MODES[1], demo_error=error)
                self.assertEqual(result.telemetry.narrative_provider, 'OFFLINE_MOCK')
                self.assertEqual(result.telemetry.status, 'RECOVERED')

    def test_normal_run_clears_previous_review_and_does_not_serialize_drafts(self):
        service = StudioService()
        episode = GoalEpisode.model_validate(generate_mock_episodes()[0])
        previous = service.broadcast(episode, mode=DEMO_MODES[1])
        review = service.demo_review
        self.assertNotIn('Zorlan Phantom', previous.model_dump_json())
        service.broadcast(episode)
        self.assertIsNone(service.demo_review)
        self.assertEqual(review.error, 'invented_player')
        self.assertIn('Zorlan Phantom', review.rejected_drafts[0].commentary)

    def test_unavailable_cases_are_not_offered_for_shot_only_episode(self):
        payload = generate_mock_episodes()[0]
        payload['events'] = payload['events'][-1:]
        episode = GoalEpisode.model_validate(payload)
        options = available_demo_errors(episode)
        self.assertNotIn('wrong_recipient', options)
        self.assertNotIn('wrong_accuracy', options)
        service = StudioService()
        for error in options:
            result = service.broadcast(episode, mode=DEMO_MODES[1], demo_error=error)
            self.assertEqual(result.telemetry.status, 'RECOVERED')
        with self.assertRaises(ValueError):
            service.broadcast(episode, mode=DEMO_MODES[1], demo_error='wrong_accuracy')


if __name__ == '__main__':
    unittest.main()
