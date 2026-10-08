"""Launch missing local services and reuse healthy existing Lab servers."""
import subprocess
import sys
import time
from pathlib import Path
import os
import socket
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
load_dotenv(ROOT / 'backend' / '.env')


class StartupError(RuntimeError):
    pass


def services():
    return [
        {'name': 'CampusHelp AI', 'app': 'examples.campushelp.app:app', 'port': 8001, 'service': 'campushelp-ai'},
        {'name': os.getenv('PRODUCT_NAME', 'LLM Integrity Lab'), 'app': 'app:app', 'port': 8000, 'service': 'llm-integrity-lab'},
    ]


def service_status(service, client):
    port = service['port']
    # An exclusive bind also detects reserved/non-HTTP ports on Windows.
    with socket.socket() as check:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            check.bind(('127.0.0.1', port))
            return 'missing'
        except OSError:
            pass
    try:
        response = client.get(f'http://127.0.0.1:{port}/api/health')
        body = response.json()
        if response.status_code != 200 or not isinstance(body, dict) or body.get('status') != 'ok':
            return 'conflict'
        if body.get('service'):
            matches = body['service'] == service['service']
        elif service['service'] == 'llm-integrity-lab':
            # Recognize instances started before explicit service IDs were added.
            matches = body.get('product') == service['name']
        else:
            matches = body.get('educational') is True and body.get('provider') == 'local deterministic mock'
        return 'ready' if matches else 'conflict'
    except (httpx.HTTPError, ValueError):
        return 'conflict'


def stop_owned(children):
    for _, child in children:
        if child.poll() is None:
            child.terminate()
    for _, child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def main():
    children = []
    try:
        with httpx.Client(timeout=1, follow_redirects=False, trust_env=False) as client:
            checks = [(service, service_status(service, client)) for service in services()]
            for service, status in checks:
                if status == 'conflict':
                    raise StartupError(f"Port {service['port']} is occupied, but it did not identify a healthy {service['name']} server. "
                                       'Close the application using that port, or retry once it finishes starting. No existing process was stopped.')
            for service, status in checks:
                if status == 'ready':
                    print(f"Already running: {service['name']} at http://127.0.0.1:{service['port']}", flush=True)
                else:
                    child = subprocess.Popen([sys.executable, '-m', 'uvicorn', service['app'], '--app-dir', str(ROOT / 'backend'),
                                              '--host', '127.0.0.1', '--port', str(service['port'])], cwd=ROOT)
                    children.append((service, child))
            if not children:
                print('Both websites are already running. Open the URLs above; stop them in their original terminal when finished.', flush=True)
                return 0
            deadline = time.monotonic() + 30
            pending = list(children)
            while pending:
                for service, child in list(pending):
                    if child.poll() is not None:
                        raise StartupError(f"{service['name']} stopped during startup (exit {child.returncode}). See the server error above.")
                    if service_status(service, client) == 'ready':
                        pending.remove((service, child))
                if pending and time.monotonic() >= deadline:
                    raise StartupError('Server startup timed out. See the server logs above.')
                if pending:
                    time.sleep(.1)
        for service, _ in children:
            print(f"Ready: {service['name']} at http://127.0.0.1:{service['port']}", flush=True)
        print('Ctrl+C stops the servers started by this launcher. Existing servers remain in their original terminal.', flush=True)
        while all(child.poll() is None for _, child in children):
            time.sleep(.5)
        failed, child = next((service, child) for service, child in children if child.poll() is not None)
        raise StartupError(f"{failed['name']} stopped (exit {child.returncode}). See the server logs above.")
    except KeyboardInterrupt:
        return 0
    except (StartupError, OSError) as error:
        print(f'[LAUNCHER] {error}', file=sys.stderr, flush=True)
        return 1
    finally:
        stop_owned(children)


if __name__ == '__main__':
    sys.exit(main())
