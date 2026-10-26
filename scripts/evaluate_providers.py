"""Opt-in comparison of the offline mock and Azure OpenAI on synthetic episodes; never part of CI."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import statistics
import time

from dotenv import load_dotenv

from src.agents.azure_runtime import AzureRuntime, azure_settings, create_azure_sdk
from src.agents.narrator import MockLLMClient
from src.agents.orchestrator import BroadcastOrchestrator
from src.analytics.schemas import GoalEpisode
from src.ingest.mock_generator import generate_mock_episodes, generate_mock_reconstruction

PERSONAS = ('TACTICAL_ANALYST', 'PASSIONATE_FAN', 'CASUAL_VIEWER')


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def summarize(name, records):
    latencies = [item['telemetry']['latency_ms'] for item in records]
    statuses = Counter(item['telemetry']['status'] for item in records)
    reasons = Counter(item['telemetry']['critic_feedback'][0].split('\n')[0][:90]
                      for item in records if item['telemetry']['critic_feedback'])
    tokens = [item['telemetry']['total_tokens'] for item in records if item['telemetry']['total_tokens'] is not None]
    return {
        'provider': name, 'cases': len(records), 'statuses': dict(statuses),
        'first_pass_rate': statuses['SUCCESS'] / len(records),
        'validated_rate': (statuses['SUCCESS'] + statuses['RECOVERED']) / len(records),
        'latency_ms': {'median': round(statistics.median(latencies), 1), 'p95': round(percentile(latencies, .95), 1),
                       'max': round(max(latencies), 1)},
        'provider_calls': sum(item['telemetry']['provider_calls'] for item in records),
        'total_tokens': sum(tokens) if tokens else None, 'top_rejection_reasons': reasons.most_common(3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--providers', nargs='+', choices=('mock', 'azure'), default=['mock', 'azure'])
    parser.add_argument('--confirm-spend', action='store_true',
                        help='Confirm that Azure OpenAI requests will spend credit from your subscription.')
    parser.add_argument('--pace-seconds', type=float, default=12,
                        help='Pause between Azure cases so a small tokens-per-minute quota is not exceeded.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env', override=False)
    if 'azure' in args.providers:
        if not args.confirm_spend:
            parser.error('Azure requests spend credit; pass --confirm-spend. No requests have been made.')
        settings = azure_settings()
        if settings is None:
            parser.error('Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT and AZURE_OPENAI_API_KEY or AZURE_OPENAI_AUTH=entra.')
    episodes = [GoalEpisode.model_validate(item) for item in generate_mock_episodes()]
    cases = [(episode, language, persona) for episode in episodes for language in ('en', 'es') for persona in PERSONAS]
    results = {}
    for provider in args.providers:
        records, closers = [], []
        if provider == 'azure':
            sdk, closers = create_azure_sdk(settings)
            runtime = AzureRuntime(sdk, settings.deployment)
        try:
            for index, (episode, language, persona) in enumerate(cases):
                focus = episode.events[0].player_id if index % 2 else None
                selection = dict(language=language, persona=persona, focus_player_id=focus)
                if provider == 'azure':
                    if index:
                        time.sleep(args.pace_seconds)
                    result = runtime.run(episode, **selection)
                else:
                    result = BroadcastOrchestrator(MockLLMClient()).run(
                        episode, **selection, reconstruction=generate_mock_reconstruction(episode))
                records.append(dict(episode=episode.goal_id, language=language, persona=persona, focus=focus,
                                    telemetry=result.telemetry.model_dump(), narrative=result.narrative.model_dump()))
                print(f'{provider}: case {index + 1}/{len(cases)} {result.telemetry.status} '
                      f'{result.telemetry.latency_ms:.0f} ms', flush=True)
        finally:
            for close in closers:
                close()
        results[provider] = records
    summary = [summarize(name, records) for name, records in results.items()]
    directory = root / '.deployment-local'
    directory.mkdir(mode=0o700, exist_ok=True)
    output = directory / 'provider-evaluation.json'
    output.touch(mode=0o600, exist_ok=True)
    output.chmod(0o600)
    output.write_text(json.dumps({
        'scope': 'Synthetic episodes; small sample, not a production benchmark. Latencies are per provider and not comparable.',
        'deployment': settings.deployment if 'azure' in args.providers else None,
        'summary': summary, 'records': results}, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'Saved {output}')


if __name__ == '__main__':
    main()
