"""Deterministic analysis, independent of files, databases and LLMs."""
import networkx as nx
from src.analytics.evidence import InferredConnection, PassEvidence, TacticalEvidence
from src.analytics.sequence import bypassed_defender_ids, scoring_passes
from src.analytics.schemas import GoalEpisode, TacticalAnalysisResponse, Zone


class TacticalEngine:
    def analyze(self, episode: GoalEpisode) -> TacticalAnalysisResponse:
        return self.analyze_with_evidence(episode)[0]

    def analyze_with_evidence(self, episode: GoalEpisode) -> tuple[TacticalAnalysisResponse, TacticalEvidence]:
        events = sorted(episode.events, key=lambda event: event.timestamp_sec)
        graph = nx.DiGraph()
        first_seen = {}
        best_score = 0
        best_pass = None
        passes = []
        connections = []
        eligible_ids = {event.event_id for event in scoring_passes(episode) if event.is_successful}
        for index, event in enumerate(events):
            first_seen.setdefault(event.player_id, index)
            if event.event_id not in eligible_ids:
                continue
            bypassed = bypassed_defender_ids(episode, event)
            score = len(bypassed)
            passes.append(PassEvidence(
                event_id=event.event_id, timestamp_sec=event.timestamp_sec, player_id=event.player_id,
                start_x=event.start_x, end_x=event.end_x,
                bypassed_defender_ids=bypassed, packing_score=score,
            ))
            if score > best_score:
                best_score, best_pass = score, event
            # Recipient inference uses the full sequence, including shots.
            if index + 1 < len(events):
                recipient = events[index + 1]
                if recipient.team == event.team and recipient.player_id != event.player_id:
                    graph.add_edge(event.player_id, recipient.player_id)
                    connections.append(InferredConnection(
                        pass_event_id=event.event_id, next_event_id=recipient.event_id,
                        passer_id=event.player_id, inferred_recipient_id=recipient.player_id,
                    ))

        centrality = nx.betweenness_centrality(graph, weight=None)
        pivot = min(
            centrality,
            key=lambda player: (-centrality[player], first_seen[player], player),
            default=None,
        )
        first = events[0]
        duration = episode.timestamp_goal - first.timestamp_sec
        if (first.event_type == 'RECOVERY' and first.is_successful
                and first.team == episode.scoring_team and duration <= 10):
            cause = 'Quick transition after recovery'
            cause_rule = 'SUCCESSFUL_RECOVERY_WITHIN_10_SECONDS'
        elif best_score >= 3:
            cause = 'Central breakthrough through a vertical pass'
            cause_rule = 'PACKING_AT_LEAST_3'
        else:
            cause = 'Positional attack'
            cause_rule = 'DEFAULT_POSITIONAL'
        analysis = TacticalAnalysisResponse(
            sequence_packing_score=best_score,
            tactical_pivot=pivot,
            breakdown_zone=self._zone(best_pass.start_x) if best_pass else None,
            tactical_cause=cause,
        )
        key = max(passes, key=lambda item: item.packing_score, default=None)
        tied = sorted((player for player in centrality if centrality[player] == centrality[pivot]),
                      key=lambda player: (first_seen[player], player)) if pivot is not None else []
        evidence = TacticalEvidence(
            scoring_team=episode.scoring_team, key_pass_event_id=key.event_id if key else None,
            passes=passes, inferred_connections=connections, pivot_scores=centrality,
            pivot_tied_player_ids=tied, cause_rule=cause_rule, first_event_id=first.event_id,
            duration_sec=duration,
            limitations=[
                'All events remain on the replay clock; only successful scoring-team passes enter packing and the pass graph.',
                'Packing uses strict X intervals against one static snapshot; Y, pressure and defensive movement are not assessed.',
                'Key pass means earliest maximum static packing, including zero; it does not identify an assist.',
                'Recipients are inferred from the immediately following event in the full sequence, never across a rival event.',
                'Pivot uses unweighted directed betweenness; ties use first chronological appearance, including zero-score ties.',
                'Tactical cause is an ordered heuristic. The legacy central-breakthrough label does not establish a central channel or causality.',
            ],
        )
        return analysis, evidence

    @staticmethod
    def _zone(x: float) -> Zone:
        if x < 33.3:
            return 'Defensive Third'
        if x < 66.6:
            return 'Middle Third'
        return 'Attacking Third'
