from flask import Blueprint, render_template, request, current_app, flash, redirect, jsonify, url_for
import os
import json
import subprocess
import requests as http_requests
from flask_login import login_required
from db import get_db

apps_bp = Blueprint('apps', __name__)

AGENT_URL = 'http://localhost:5001'


def get_local_apps():
    apps = []
    apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
    if not os.path.exists(apps_dir):
        return apps
    for entry in os.listdir(apps_dir):
        app_dir = os.path.join(apps_dir, entry)
        meta_path = os.path.join(app_dir, 'app.json')
        if os.path.isdir(app_dir) and os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                meta['folder'] = entry
                apps.append(meta)
            except Exception as e:
                print(f"Error loading {meta_path}: {e}")
    return apps


def get_remote_apps(repo_url):
    apps = []
    try:
        resp = http_requests.get(repo_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
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


@apps_bp.route('/apps/<name>')
@login_required
def app_detail(name):
    apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
    app_dir = os.path.join(apps_dir, name)
    meta_path = os.path.join(app_dir, 'app.json')
    compose_path = os.path.join(app_dir, 'docker-compose.yaml')
    dockerfile_path = os.path.join(app_dir, 'Dockerfile')
    if not os.path.isdir(app_dir) or not os.path.isfile(meta_path):
        flash("App not found.", "error")
        return redirect(url_for('apps.list_apps'))
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as e:
        flash(f"Error loading app metadata: {e}", "error")
        return redirect(url_for('apps.list_apps'))
    compose_content = ''
    if os.path.isfile(compose_path):
        with open(compose_path) as f:
            compose_content = f.read()
    dockerfile_content = ''
    if os.path.isfile(dockerfile_path):
        with open(dockerfile_path) as f:
            dockerfile_content = f.read()
    return render_template('app_detail.html',
                           meta=meta,
                           name=name,
                           compose=compose_content,
                           dockerfile=dockerfile_content)


@apps_bp.route('/apps/<name>/deploy', methods=['POST'])
@login_required
def deploy_app(name):
    apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
    app_dir = os.path.join(apps_dir, name)
    meta_path = os.path.join(app_dir, 'app.json')
    if not os.path.isdir(app_dir) or not os.path.isfile(meta_path):
        flash("App not found.", "error")
        return redirect(url_for('apps.list_apps'))
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as e:
        flash(f"Error loading metadata: {e}", "error")
        return redirect(url_for('apps.list_apps'))
    compose_edited = request.form.get('compose', '')
    compose_path = os.path.join(app_dir, 'docker-compose.yaml')
    if compose_edited:
        with open(compose_path, 'w') as f:
            f.write(compose_edited)
    dockerfile_edited = request.form.get('dockerfile', '')
    dockerfile_path = os.path.join(app_dir, 'Dockerfile')
    if dockerfile_edited:
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_edited)
    try:
        payload = {'folder': name}
        resp = http_requests.post(f'{AGENT_URL}/api/deploy', json=payload, timeout=30)
        if resp.status_code != 200:
            flash(f"Deploy failed: {resp.text}", "error")
            return redirect(url_for('apps.app_detail', name=name))
        db = get_db()
        db.execute('''
            INSERT OR REPLACE INTO deployed_apps (id, name, folder, port, status)
            VALUES (nextval('deployed_app_id_seq'), ?, ?, ?, 'running')
        ''', [meta['name'], name, meta.get('port', 0)])
        flash(f"{meta['name']} deployed successfully", "success")
    except Exception as e:
        flash(f"Deploy error: {e}", "error")
    return redirect(url_for('apps.deployed_list'))


@apps_bp.route('/deployed')
@login_required
def deployed_list():
    db = get_db()
    rows = db.execute('SELECT id, name, folder, port, status, created_at, updated_at FROM deployed_apps ORDER BY id DESC').fetchall()
    deployed = []
    for r in rows:
        deployed.append({
            'id': r[0], 'name': r[1], 'folder': r[2],
            'port': r[3], 'status': r[4],
            'created_at': r[5], 'updated_at': r[6]
        })
    return render_template('deployed.html', deployed=deployed)


@apps_bp.route('/deployed/<name>/status')
@login_required
def deployed_status(name):
    try:
        resp = http_requests.get(f'{AGENT_URL}/api/deployed/{name}/status', timeout=5)
        if resp.status_code == 200:
            return jsonify(resp.json())
        return jsonify({'error': resp.text}), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@apps_bp.route('/deployed/<name>/logs')
@login_required
def deployed_logs(name):
    return render_template('app_logs.html', name=name)


@apps_bp.route('/deployed/<name>/logs/raw')
@login_required
def deployed_logs_raw(name):
    try:
        resp = http_requests.get(f'{AGENT_URL}/api/deployed/{name}/logs', timeout=5)
        if resp.status_code == 200:
            return resp.text, 200, {'Content-Type': 'text/plain'}
        return resp.text, resp.status_code
    except Exception as e:
        return str(e), 500


@apps_bp.route('/deployed/<name>/down', methods=['POST'])
@login_required
def deployed_down(name):
    try:
        resp = http_requests.post(f'{AGENT_URL}/api/deployed/{name}/down', timeout=30)
        if resp.status_code != 200:
            flash(f"Error stopping app: {resp.text}", "error")
        else:
            db = get_db()
            db.execute('UPDATE deployed_apps SET status = ? WHERE name = ?', ['stopped', name])
            flash("App stopped", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('apps.deployed_list'))


@apps_bp.route('/deploy_command', methods=['POST'])
@login_required
def deploy_command():
    command = request.form.get('command')
    if command:
        if not command.strip().startswith("podman "):
            flash("Invalid command. Only 'podman' commands are allowed.", "error")
            return redirect(request.referrer or '/apps')
        try:
            if ";" in command or "&&" in command or "|" in command or ">" in command or "<" in command:
                flash("Invalid command format.", "error")
                return redirect(request.referrer or '/apps')
            import shlex
            subprocess.Popen(shlex.split(command))
            flash("App deployed successfully", "success")
        except Exception as e:
            flash(f"Error deploying app: {e}", "error")
    else:
        flash("No command provided", "error")
    return redirect(request.referrer or '/apps')
