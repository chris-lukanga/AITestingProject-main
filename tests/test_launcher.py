"""Real-process launcher checks: ownership, reuse, conflicts and startup failure."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNNER = '''
import _thread, json, os, threading, time
from pathlib import Path
import run_lab
run_lab.services = lambda: json.loads(os.environ['LAUNCH_TEST_SERVICES'])
stop = Path(os.environ['LAUNCH_TEST_STOP'])
def watch():
    while not stop.exists():
        time.sleep(.05)
    _thread.interrupt_main()
threading.Thread(target=watch, daemon=True).start()
raise SystemExit(run_lab.main())
'''


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def service_configs():
    import run_lab
    configs = run_lab.services()
    ports = set()
    for config in configs:
        port = free_port()
        while port in ports:
            port = free_port()
        config['port'] = port
        ports.add(port)
    return configs


def launch(configs, tmp_path, name):
    stop = tmp_path / (name + '.stop')
    environment = dict(os.environ, LAUNCH_TEST_SERVICES=json.dumps(configs), LAUNCH_TEST_STOP=str(stop),
                       LAB_DATA_DIR=str(tmp_path / 'lab'))
    process = subprocess.Popen([sys.executable, '-u', '-c', RUNNER], cwd=ROOT, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process, stop


def await_ready(configs, process):
    deadline = time.monotonic() + 30
    with httpx.Client(timeout=.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                out, err = process.communicate()
                raise AssertionError(f'Server startup failed: {out}\n{err}')
            try:
                if all(client.get(f"http://127.0.0.1:{service['port']}/api/health").status_code == 200 for service in configs):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.1)
    raise AssertionError('Servers did not become ready.')


def stop_launcher(process, stop):
    stop.touch()
    return process.communicate(timeout=15)


def test_repeated_launch_reuses_real_servers_and_preserves_owner(tmp_path):
    configs = service_configs()
    owner, stop = launch(configs, tmp_path, 'owner')
    try:
        await_ready(configs, owner)
        repeated, repeated_stop = launch(configs, tmp_path, 'repeated')
        out, err = repeated.communicate(timeout=10)
        assert repeated.returncode == 0, err
        assert out.count('Already running:') == 2
        assert 'Both websites are already running' in out
        assert 'Traceback' not in err
        assert owner.poll() is None
        await_ready(configs, owner)
    finally:
        out, err = stop_launcher(owner, stop)
    assert owner.returncode == 0, err
    assert out.count('Ready:') == 2


def test_partial_launch_starts_only_missing_service(tmp_path):
    configs = service_configs()
    demo = configs[0]
    existing = subprocess.Popen([sys.executable, '-m', 'uvicorn', demo['app'], '--host', '127.0.0.1', '--port', str(demo['port'])],
                                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process = stop = None
    try:
        await_ready([demo], existing)
        process, stop = launch(configs, tmp_path, 'partial')
        await_ready(configs, process)
        out, err = stop_launcher(process, stop)
        assert process.returncode == 0, err
        assert out.count('Already running:') == 1
        assert 'Ready: CampusHelp AI' not in out
        assert existing.poll() is None
        assert httpx.get(f"http://127.0.0.1:{demo['port']}/api/health", trust_env=False).status_code == 200
    finally:
        if process is not None and process.poll() is None:
            stop_launcher(process, stop)
        existing.terminate()
        existing.wait(timeout=10)


def test_unrelated_port_conflict_has_clear_error_and_preserves_listener(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"unrelated-service"}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    configs = service_configs()
    configs[0]['port'] = server.server_address[1]
    try:
        process, stop = launch(configs, tmp_path, 'conflict')
        out, err = process.communicate(timeout=10)
        assert process.returncode == 1
        assert f"Port {configs[0]['port']} is occupied" in err
        assert 'Traceback' not in err
        assert httpx.get(f"http://127.0.0.1:{configs[0]['port']}/api/health", trust_env=False).status_code == 200
        # Preflight rejected before starting even the other, available service.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', configs[1]['port']))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_startup_failure_returns_nonzero_without_launcher_traceback(tmp_path):
    configs = service_configs()
    configs[0]['app'] = 'missing_lab_test_module:app'
    process, stop = launch(configs, tmp_path, 'failure')
    out, err = process.communicate(timeout=15)
    assert process.returncode == 1
    assert 'stopped during startup' in err
    assert 'Traceback' not in err
