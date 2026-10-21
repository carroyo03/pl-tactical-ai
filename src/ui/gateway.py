"""Run the studio and its bounded ingress as supervised child processes."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time


def configuration_values():
    values = {}
    for variable, default, maximum in (
        ('STUDIO_REQUEST_RATE', 20, 1000), ('STUDIO_CONNECTION_LIMIT', 32, 128),
        ('STUDIO_GATEWAY_PORT', 8080, 65535), ('STUDIO_INTERNAL_PORT', 8501, 65535),
    ):
        value = int(os.getenv(variable, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError('Invalid studio capacity configuration')
        values[variable] = value
    if values['STUDIO_GATEWAY_PORT'] == values['STUDIO_INTERNAL_PORT']:
        raise ValueError('Studio listener ports must differ')
    return values


def main():
    values = configuration_values()
    template = Path(__file__).with_name('nginx.conf').read_text()
    for key, value in values.items():
        template = template.replace('__' + key.removeprefix('STUDIO_') + '__', str(value))
    with tempfile.NamedTemporaryFile(mode='w', prefix='tactical-nginx-', suffix='.conf', delete=False) as config:
        config.write(template)
        configuration = config.name
    subprocess.run(['nginx', '-t', '-c', configuration], check=True)
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([
            sys.executable, '-m', 'streamlit', 'run', 'src/ui/app.py',
            '--server.address', '127.0.0.1', '--server.port', str(values['STUDIO_INTERNAL_PORT']), '--server.headless', 'true',
        ]))
        children.append(subprocess.Popen(['nginx', '-c', configuration, '-g', 'daemon off;']))
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError('A studio process exited unexpectedly')
            time.sleep(.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        Path(configuration).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
