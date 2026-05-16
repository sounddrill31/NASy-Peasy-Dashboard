from flask import Blueprint, render_template, request, current_app, flash
import os
import yaml
import requests
import subprocess
from flask_login import login_required

apps_bp = Blueprint('apps', __name__)

def get_local_apps():
    apps = []
    apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
    if os.path.exists(apps_dir):
        for filename in os.listdir(apps_dir):
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                filepath = os.path.join(apps_dir, filename)
                try:
                    with open(filepath, 'r') as f:
                        app_data = yaml.safe_load(f)
                        if app_data:
                            apps.append(app_data)
                except Exception as e:
                    print(f"Error loading {filepath}: {e}")
    return apps

def get_remote_apps(repo_url):
    apps = []
    try:
        response = requests.get(repo_url, timeout=5)
        if response.status_code == 200:
            data = yaml.safe_load(response.text)
            if isinstance(data, list):
                 apps.extend(data)
            elif isinstance(data, dict) and 'apps' in data:
                 apps.extend(data['apps'])
    except Exception as e:
        print(f"Error fetching remote repo {repo_url}: {e}")
    return apps

@apps_bp.route('/apps')
@login_required
def list_apps():
    local_apps = get_local_apps()
    repo_url = request.args.get('repo_url')
    remote_apps = []
    if repo_url:
        remote_apps = get_remote_apps(repo_url)
    all_apps = local_apps + remote_apps
    return render_template('apps.html', apps=all_apps, repo_url=repo_url)

@apps_bp.route('/deploy_app', methods=['POST'])
@login_required
def deploy_app():
    command = request.form.get('command')
    if command:
        if not command.strip().startswith("podman "):
            flash("Invalid command. Only 'podman' commands are allowed.", "error")
            return redirect(request.referrer or '/apps')

        try:
            # Basic validation to prevent arbitrary bash injection, although not foolproof
            if ";" in command or "&&" in command or "|" in command or ">" in command or "<" in command:
                 flash("Invalid command format.", "error")
                 return redirect(request.referrer or '/apps')

            import shlex; subprocess.Popen(shlex.split(command)) # Use split to avoid shell=True
            flash("App deployed successfully", "success")
        except Exception as e:
            flash(f"Error deploying app: {e}", "error")
    else:
        flash("No command provided", "error")
    return redirect(request.referrer or '/apps')
