import subprocess
import json
import time
import socket
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import shutil
import tempfile

try:
    import requests
except ImportError:
    requests = None

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_host_data.json')
POLL_INTERVAL = 10

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

_ts_available = False
_ts_api_mode = None
_ts_api_key = None
_ts_tailnet = None

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host_agent.log')


def log(msg):
    print(msg, file=sys.stderr)


def load_env():
    path = ENV_FILE
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())


def probe_tailscale():
    global _ts_available, _ts_api_mode, _ts_api_key, _ts_tailnet

    key = os.environ.get('TAILSCALE_API_KEY') or ''
    tailnet = os.environ.get('TAILSCALE_TAILNET') or ''

    if key and tailnet and requests is not None:
        url = f'https://api.tailscale.com/api/v2/tailnet/{tailnet}/devices'
        try:
            r = requests.get(url, auth=(key, ''), timeout=5)
            if r.status_code == 200:
                _ts_api_mode = 'api'
                _ts_api_key = key
                _ts_tailnet = tailnet
                _ts_available = True
                log('tailscale: using API v2')
                return
            else:
                log(f'tailscale: API returned {r.status_code}')
        except Exception as e:
            log(f'tailscale: API error - {e}')

    try:
        r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            _ts_api_mode = 'cli'
            _ts_available = True
            log('tailscale: using local CLI')
            return
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f'tailscale: CLI probe error - {e}')

    _ts_available = False
    log('tailscale: not available (set TAILSCALE_API_KEY+TAILSCALE_TAILNET in .env or start tailscaled)')


def get_podman_containers():
    try:
        result = subprocess.run(['podman', 'ps', '-a', '--format', 'json'], capture_output=True, text=True, check=True)
        if result.stdout.strip():
            return json.loads(result.stdout)
        return []
    except Exception as e:
        log(f"podman error: {e}")
        return []


def get_tailscale_status():
    if not _ts_available:
        return None

    if _ts_api_mode == 'api':
        try:
            url = f'https://api.tailscale.com/api/v2/tailnet/{_ts_tailnet}/devices'
            r = requests.get(url, auth=(_ts_api_key, ''), timeout=5)
            if r.status_code != 200:
                return None
            body = r.json()
            devices = body.get('devices', [])
            hostname = socket.gethostname()
            self_device = None
            for d in devices:
                if d.get('hostname') == hostname or d.get('name', '').startswith(hostname):
                    self_device = d
                    break
            if not self_device and devices:
                self_device = devices[0]
            return {
                'Self': {
                    'TailscaleIPs': self_device.get('addresses', []) if self_device else [],
                    'HostName': self_device.get('hostname', '') if self_device else '',
                    'Online': self_device.get('online', False) if self_device else False,
                },
                'devices': devices,
            }
        except Exception as e:
            log(f'tailscale API error: {e}')
            return None

    if _ts_api_mode == 'cli':
        try:
            r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except Exception as e:
            log(f'tailscale CLI error: {e}')
        return None


def is_cockpit_reachable():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(('localhost', 9090))
        s.shutdown(socket.SHUT_RDWR)
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


def collect():
    data = {
        'containers': get_podman_containers(),
        'tailscale': get_tailscale_status(),
        'cockpit': is_cockpit_reachable(),
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)


def collector_loop():
    while True:
        collect()
        time.sleep(POLL_INTERVAL)


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PODMAN = '/usr/bin/podman'
SYSTEM_PODMAN_COMPOSE = '/usr/bin/podman-compose'


def get_compose_path(folder):
    deploy_path = os.path.join(PROJECT_DIR, 'deployments', folder, 'docker-compose.yaml')
    if os.path.isfile(deploy_path):
        return deploy_path
    return os.path.join(PROJECT_DIR, 'templates', 'apps', folder, 'docker-compose.yaml')


class DeployHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log(f"[api] {format % args}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_text(self, text, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(text.encode())

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode()
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({'error': 'invalid json'}, 400)
            return

        if self.path == '/api/deploy':
            folder = payload.get('folder', '')
            if not folder:
                self._send_json({'error': 'folder required'}, 400)
                return
            compose_file = get_compose_path(folder)
            if not os.path.isfile(compose_file):
                self._send_json({'error': f'docker-compose.yaml not found in {folder}'}, 400)
                return
            try:
                result = subprocess.run(
                    [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', f'nasypeasy-{folder}', 'up', '-d'],
                    capture_output=True, text=True, timeout=180
                )
                if result.returncode != 0:
                    self._send_json({'error': result.stderr or result.stdout}, 500)
                    return
                self._send_json({'ok': True, 'output': result.stdout})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        if self.path.startswith('/api/deployed/') and self.path.endswith('/down'):
            name = self.path.split('/')[3]
            compose_file = get_compose_path(name)
            if not os.path.isfile(compose_file):
                self._send_json({'error': 'compose file not found'}, 400)
                return
            try:
                result = subprocess.run(
                    [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', f'nasypeasy-{name}', 'down'],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode != 0:
                    self._send_json({'error': result.stderr or result.stdout}, 500)
                    return
                self._send_json({'ok': True, 'output': result.stdout})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        if self.path.startswith('/api/deployed/') and self.path.endswith('/up'):
            name = self.path.split('/')[3]
            compose_file = get_compose_path(name)
            if not os.path.isfile(compose_file):
                self._send_json({'error': 'compose file not found'}, 400)
                return
            try:
                result = subprocess.run(
                    [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', f'nasypeasy-{name}', 'up', '-d'],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode != 0:
                    self._send_json({'error': result.stderr or result.stdout}, 500)
                    return
                self._send_json({'ok': True, 'output': result.stdout})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        if self.path.startswith('/api/deployed/') and self.path.endswith('/delete'):
            name = self.path.split('/')[3]
            remove_volumes = payload.get('remove_volumes', False)
            compose_file = get_compose_path(name)
            if not os.path.isfile(compose_file):
                self._send_json({'error': 'compose file not found'}, 400)
                return
            try:
                cmd = [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', f'nasypeasy-{name}', 'down']
                if remove_volumes:
                    cmd.append('-v')
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                subprocess.run([SYSTEM_PODMAN, 'network', 'rm', f'{name}_default'],
                               capture_output=True, text=True, timeout=10)
                self._send_json({'ok': True})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        self._send_json({'error': 'not found'}, 404)

    def do_GET(self):
        if self.path.startswith('/api/deployed/') and self.path.endswith('/status'):
            name = self.path.split('/')[3]
            compose_file = get_compose_path(name)
            try:
                result = subprocess.run(
                    [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', f'nasypeasy-{name}', 'ps', '--format', 'json'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    self._send_json(json.loads(result.stdout))
                else:
                    self._send_json({'status': 'stopped'})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)
            return

        if self.path.startswith('/api/deployed/') and self.path.endswith('/logs'):
            name = self.path.split('/')[3]
            compose_file = get_compose_path(name)
            try:
                project_name = f'nasypeasy-{name}'
                ps_result = subprocess.run(
                    [SYSTEM_PODMAN_COMPOSE, '-f', compose_file, '-p', project_name, 'ps', '--format', 'json'],
                    capture_output=True, text=True, timeout=10
                )
                container_ids = []
                if ps_result.returncode == 0 and ps_result.stdout.strip():
                    services = json.loads(ps_result.stdout)
                    if isinstance(services, list):
                        for s in services:
                            if s.get('Id'):
                                container_ids.append(s['Id'])
                    elif isinstance(services, dict):
                        for k, v in services.items():
                            if isinstance(v, dict) and v.get('Id'):
                                container_ids.append(v['Id'])
                if not container_ids:
                    self._send_text('No running containers for this app.\n')
                    return
                log_lines = []
                for cid in container_ids:
                    try:
                        r = subprocess.run(
                            [SYSTEM_PODMAN, 'logs', '--tail', '100', cid],
                            capture_output=True, text=True, timeout=5
                        )
                        if r.stdout:
                            log_lines.append(f"=== {cid[:12]} ===\n{r.stdout}")
                        if r.stderr:
                            log_lines.append(f"=== {cid[:12]} (stderr) ===\n{r.stderr}")
                    except Exception:
                        pass
                self._send_text('\n'.join(log_lines) if log_lines else 'No logs available.\n')
            except Exception as e:
                self._send_text(f'Error: {e}\n', 500)
            return

        self._send_json({'error': 'not found'}, 404)


def api_server():
    server = HTTPServer(('127.0.0.1', 5001), DeployHandler)
    log(f"[api] HTTP server on http://127.0.0.1:5001")
    server.serve_forever()


def daemonize():
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/dev/null', 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(LOG_FILE, 'a') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())


def main():
    if '--daemon' in sys.argv:
        daemonize()
    load_env()
    log(f"Host agent starting (poll interval: {POLL_INTERVAL}s)")
    log(f"Data file: {DATA_FILE}")
    log(f"Log file: {LOG_FILE}")
    probe_tailscale()
    t = threading.Thread(target=api_server, daemon=True)
    t.start()
    collector_loop()


if __name__ == '__main__':
    main()
