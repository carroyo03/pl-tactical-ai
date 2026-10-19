import json
import uuid
from pathlib import Path

def generate_mock_goal_episode():
    match_id = "MATCH_PL_SYNTHETIC_01"
    goal_id = str(uuid.uuid4())[:8]

    # 4 events previous to goal sequence (20 seconds of transition)
    events = [
        {
            "event_id": "ev_01",
            "match_id": match_id,
            "timestamp_sec": 1420.0,
            "period": 2,
            "team": "HOME",
            "player_id": "P_04",
            "player_name": "Caicedo",
            "event_type": "RECOVERY",
            "start_x": 35.0,
            "start_y": 48.0,
            "end_x": 35.0,
            "end_y": 48.0,
            "is_successful": True
        },
        {
            "event_id": "ev_02",
            "match_id": match_id,
            "timestamp_sec": 1423.5,
            "period": 2,
            "team": "HOME",
            "player_id": "P_04",
            "player_name": "Caicedo",
            "event_type": "PASS",
            "start_x": 35.0,
            "start_y": 48.0,
            "end_x": 72.0,
            "end_y": 55.0,
            "is_successful": True
        },
        {
            "event_id": "ev_03",
            "match_id": match_id,
            "timestamp_sec": 1426.0,
            "period": 2,
            "team": "HOME",
            "player_id": "P_10",
            "player_name": "Palmer",
            "event_type": "PASS",
            "start_x": 72.0,
            "start_y": 55.0,
            "end_x": 88.0,
            "end_y": 45.0,
            "is_successful": True
        },
        {
            "event_id": "ev_04",
            "match_id": match_id,
            "timestamp_sec": 1428.2,
            "period": 2,
            "team": "HOME",
            "player_id": "P_09",
            "player_name": "Jackson",
            "event_type": "SHOT",
            "start_x": 88.0,
            "start_y": 45.0,
            "end_x": 100.0,
            "end_y": 50.0,
            "is_successful": True
        }
    ]

    # Defensive positions at the moment of the goal (snapshot)
    defenders_snapshot = [
        {"player_id": "DEF_01", "x": 50.0, "y": 40.0},
        {"player_id": "DEF_02", "x": 52.0, "y": 60.0},
        {"player_id": "DEF_03", "x": 65.0, "y": 50.0},
        {"player_id": "DEF_04", "x": 78.0, "y": 45.0},
        {"player_id": "DEF_05", "x": 80.0, "y": 55.0}
    ]

    payload = {
        "goal_id": goal_id,
        "match_id": match_id,
        "timestamp_goal": 1428.2,
        "scoring_team": "HOME",
        "conceding_team": "AWAY",
        "events": events,
        "defenders_snapshot": defenders_snapshot
    }

    output_dir = Path("data/raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / "sample_goal_episode.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Mock data generated in: {file_path}")

if __name__ == "__main__":
    generate_mock_goal_episode()