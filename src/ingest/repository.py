"""In-memory episode storage with no tactical logic."""
from pathlib import Path
from threading import RLock
import duckdb
from src.analytics.schemas import GoalEpisode


class DuckDBRepository:
    def __init__(self):
        self._lock = RLock()
        self._connection = duckdb.connect(':memory:')
        self._connection.execute(
            'CREATE TABLE episodes (goal_id VARCHAR PRIMARY KEY, payload JSON NOT NULL)'
        )

    def save(self, episode: GoalEpisode) -> None:
        with self._lock:
            self._connection.execute(
                'INSERT OR REPLACE INTO episodes VALUES (?, ?)',
                [episode.goal_id, episode.model_dump_json()],
            )

    def load_json(self, path: str | Path) -> GoalEpisode:
        episode = GoalEpisode.model_validate_json(Path(path).read_text(encoding='utf-8'))
        self.save(episode)
        return episode

    def get(self, goal_id: str) -> GoalEpisode:
        with self._lock:
            row = self._connection.execute(
                'SELECT payload FROM episodes WHERE goal_id = ?', [goal_id]
            ).fetchone()
        if row is None:
            raise KeyError(goal_id)
        return GoalEpisode.model_validate_json(row[0])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def list_goal_ids(self) -> list[str]:
        with self._lock:
            rows = self._connection.execute('SELECT goal_id FROM episodes ORDER BY goal_id').fetchall()
        return [row[0] for row in rows]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
