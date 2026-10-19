"""Deterministic analysis, independent of files, databases and LLMs."""
import networkx as nx
from src.analytics.schemas import GoalEpisode, TacticalAnalysisResponse, Zone


class TacticalEngine:
    def analyze(self, episode: GoalEpisode) -> TacticalAnalysisResponse:
        events = sorted(episode.events, key=lambda event: event.timestamp_sec)
        graph = nx.DiGraph()
        first_seen = {}
        best_score = 0
        best_pass = None
        for index, event in enumerate(events):
            first_seen.setdefault(event.player_id, index)
            if event.event_type != 'PASS' or not event.is_successful:
                continue
            score = sum(
                event.start_x < defender.x < event.end_x
                for defender in episode.defenders_snapshot
            )
            if score > best_score:
                best_score, best_pass = score, event
            # Recipient inference uses the full sequence, including shots.
            if index + 1 < len(events):
                recipient = events[index + 1]
                if recipient.team == event.team and recipient.player_id != event.player_id:
                    graph.add_edge(event.player_id, recipient.player_id)

        centrality = nx.betweenness_centrality(graph, weight=None)
        pivot = min(
            centrality,
            key=lambda player: (-centrality[player], first_seen[player], player),
            default=None,
        )
        first = events[0]
        duration = episode.timestamp_goal - first.timestamp_sec
        if first.event_type == 'RECOVERY' and duration <= 10:
            cause = 'Quick transition after recovery'
        elif best_score >= 3:
            cause = 'Central breakthrough through a vertical pass'
        else:
            cause = 'Positional attack'
        return TacticalAnalysisResponse(
            sequence_packing_score=best_score,
            tactical_pivot=pivot,
            breakdown_zone=self._zone(best_pass.start_x) if best_pass else None,
            tactical_cause=cause,
        )

    @staticmethod
    def _zone(x: float) -> Zone:
        if x < 33.3:
            return 'Defensive Third'
        if x < 66.6:
            return 'Middle Third'
        return 'Attacking Third'
