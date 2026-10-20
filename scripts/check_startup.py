"""Check real local server processes from a clean locked installation."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def read(url):
    with urlopen(url, timeout=1) as response:
        return response.read().decode()


def check(command, ready_path, verify):
    selected_port = port()
    command = [part.replace('{port}', str(selected_port)) for part in command]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('AZURE_OPENAI_') and key != 'API_BASE_URL'}
    with tempfile.TemporaryFile(mode='w+') as logs:
        child = subprocess.Popen(command, stdout=logs, stderr=logs, env=environment)
        try:
            base = f'http://127.0.0.1:{selected_port}'
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    logs.seek(0)
                    raise RuntimeError(logs.read())
                try:
                    read(base + ready_path)
                    break
                except (URLError, TimeoutError):
                    time.sleep(.1)
            else:
                logs.seek(0)
                raise RuntimeError('Server readiness timed out: ' + logs.read())
            verify(base)
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def verify_api(base):
    goals = json.loads(read(base + '/goals'))
    assert len(goals) == 3
    response = json.loads(read(base + f'/goals/{goals[0]}/broadcast'))
    assert response['telemetry']['narrative_provider'] == 'OFFLINE_MOCK'
    assert response['telemetry']['status'] == 'SUCCESS'
    assert len(response['reconstruction']['frames']) == 4
    legacy = json.loads(read(base + f'/goals/{goals[0]}/intelligence'))
    assert set(legacy) == {'episode', 'analysis', 'narrative'}
    print('API: real HTTP startup, 3 episodes, offline broadcast, legacy contract and reconstruction OK')


def main():
    check([sys.executable, '-m', 'uvicorn', 'src.api.app:app', '--host', '127.0.0.1',
           '--port', '{port}', '--log-level', 'warning'], '/goals', verify_api)
    check([sys.executable, '-m', 'streamlit', 'run', 'src/ui/app.py', '--server.address', '127.0.0.1',
           '--server.port', '{port}', '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
          '/_stcore/health', lambda base: print('Streamlit: real HTTP startup and health OK'))


if __name__ == '__main__':
    main()
