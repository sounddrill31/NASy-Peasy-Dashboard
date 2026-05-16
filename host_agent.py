import subprocess
import json
import time
import socket
import os
import sys

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
                print('tailscale: using API v2', file=sys.stderr)
                return
            else:
                print(f'tailscale: API returned {r.status_code}', file=sys.stderr)
        except Exception as e:
            print(f'tailscale: API error - {e}', file=sys.stderr)

    try:
        r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            _ts_api_mode = 'cli'
            _ts_available = True
            print('tailscale: using local CLI', file=sys.stderr)
            return
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f'tailscale: CLI probe error - {e}', file=sys.stderr)

    _ts_available = False
    print('tailscale: not available (set TAILSCALE_API_KEY+TAILSCALE_TAILNET in .env or start tailscaled)', file=sys.stderr)


def get_podman_containers():
    try:
        result = subprocess.run(['podman', 'ps', '-a', '--format', 'json'], capture_output=True, text=True, check=True)
        if result.stdout.strip():
            return json.loads(result.stdout)
        return []
    except Exception as e:
        print(f"podman error: {e}", file=sys.stderr)
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
            print(f'tailscale API error: {e}', file=sys.stderr)
            return None

    if _ts_api_mode == 'cli':
        try:
            r = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout)
        except Exception as e:
            print(f'tailscale CLI error: {e}', file=sys.stderr)
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


LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host_agent.log')


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
    print(f"Host agent starting (poll interval: {POLL_INTERVAL}s)", file=sys.stderr)
    print(f"Data file: {DATA_FILE}", file=sys.stderr)
    print(f"Log file: {LOG_FILE}", file=sys.stderr)
    probe_tailscale()
    while True:
        collect()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
