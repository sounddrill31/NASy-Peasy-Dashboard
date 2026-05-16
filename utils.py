import json
import os

HOST_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_host_data.json')

def get_podman_containers():
    try:
        with open(HOST_DATA_FILE) as f:
            data = json.load(f)
        return data.get('containers', [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def get_tailscale_status():
    try:
        with open(HOST_DATA_FILE) as f:
            data = json.load(f)
        return data.get('tailscale')
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def is_cockpit_reachable():
    try:
        with open(HOST_DATA_FILE) as f:
            data = json.load(f)
        return data.get('cockpit', False)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
