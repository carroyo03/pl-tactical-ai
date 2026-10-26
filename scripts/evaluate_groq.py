"""Bounded, opt-in free-plan evaluation; never part of offline CI."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from src.agents.groq_client import GroqRuntime, MODELS
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-free-plan', action='store_true',
                        help='Confirm in Groq Console that billing is not enabled before using this flag.')
    parser.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    parser.add_argument('--language', choices=('both', 'en', 'es'), default='both')
    parser.add_argument('--cases-per-model', type=int, choices=range(1, 7), default=6)
    args = parser.parse_args()
    if not args.confirm_free_plan:
        parser.error('Free-plan confirmation is required; no requests have been made.')
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env', override=False)
    implementation = sha256((root / 'src/agents/groq_client.py').read_bytes()).hexdigest()
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        parser.error('Local model credentials are missing.')
    if len(args.models) > 3 or len(set(args.models)) != len(args.models):
        parser.error('Choose at most three distinct models.')
    episodes = [GoalEpisode.model_validate(item) for item in generate_mock_episodes()]
    records = []
    directory = root / '.deployment-local'
    directory.mkdir(mode=0o700, exist_ok=True)
    output = directory / 'groq-evaluation.json'
    output.touch(mode=0o600, exist_ok=True)
    output.chmod(0o600)
    cases = [(episode, language) for episode in episodes for language in ('en', 'es')
             if args.language == 'both' or args.language == language]
    for model in args.models:
        runtime = GroqRuntime(key, model)
        try:
            for index, (episode, language) in enumerate(cases[:args.cases_per_model]):
                # Pace requests conservatively; returned quota limits still take precedence.
                if records:
                    time.sleep(35)
                persona = ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER')[index % 3]
                focus = episode.events[0].player_id if index % 2 else None
                result = runtime.run(episode, language=language, persona=persona, focus_player_id=focus)
                records.append(dict(model=model, episode=episode.goal_id, language=language,
                                    persona=persona, focus=focus, telemetry=result.telemetry.model_dump(),
                                    narrative=result.narrative.model_dump()))
                output.write_text(json.dumps({'scope': 'Synthetic episode narration; not a production benchmark',
                                              'prompt_revision': 'verified-reference-v1',
                                              'implementation_sha256': implementation,
                                              'records': records}, ensure_ascii=False, indent=2))
                print(f'{model}: case {index + 1}/{min(args.cases_per_model, len(cases))}, '
                      f'{result.telemetry.status}, {result.telemetry.latency_ms:.0f} ms', flush=True)
        finally:
            runtime.transport.close()
    for model in args.models:
        subset = [record for record in records if record['model'] == model]
        print(model, dict(Counter(item['telemetry']['status'] for item in subset)))
    print('Private evaluation saved. Review narrative quality before selecting a default model.')


if __name__ == '__main__':
    main()
