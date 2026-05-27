import os
import json
import subprocess
import re
import shutil
import threading
import shlex
import requests as http_requests
from flask import Blueprint, render_template, request, current_app, flash, redirect, jsonify, url_for
from flask_login import login_required
from string import Template as StringTemplate
from db import get_db

apps_bp = Blueprint('apps', __name__)

AGENT_URL = 'http://localhost:5001'


def get_local_apps():
    apps = []
    apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
    if not os.path.exists(apps_dir):
        return apps
    for entry in sorted(os.listdir(apps_dir)):
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


def _repo_dir(source):
    name = source.rstrip('/').rstrip('.git')
    name = name.replace('https://', '').replace('http://', '').replace('git@', '')
    name = name.replace(':', '_').replace('/', '_').replace('.', '_')
    return os.path.join(current_app.root_path, 'repos', name)


def import_apps_from_source(source):
    """Import apps from a local folder path or git repo URL.
    Each subfolder must contain app.json + docker-compose.yaml.
    Returns (count, error_messages).
    """
    try:
        if source.startswith(('http://', 'https://', 'git@', 'git://')):
            repo_dir = _repo_dir(source)
            repo_exists = os.path.isdir(repo_dir)
            os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
            try:
                if repo_exists:
                    r = subprocess.run(['git', '-C', repo_dir, 'pull', '--ff-only'],
                                       capture_output=True, text=True, timeout=60)
                else:
                    r = subprocess.run(['git', 'clone', '--depth', '1', source, repo_dir],
                                       capture_output=True, text=True, timeout=120)
            except FileNotFoundError:
                return 0, "Git is not accessible from the web server. Run: sudo dnf install git (or apt install git)"
            if r.returncode != 0:
                return 0, f"Git {'pull' if repo_exists else 'clone'} failed: {r.stderr.strip()}"
            scan_dir = repo_dir
        elif os.path.isdir(source):
            scan_dir = source
        else:
            return 0, "Invalid source: not a directory or git repo URL"

        apps_dir = os.path.join(current_app.root_path, 'templates', 'apps')
        os.makedirs(apps_dir, exist_ok=True)
        imported = 0
        errs = []

        for entry in sorted(os.listdir(scan_dir)):
            app_dir = os.path.join(scan_dir, entry)
            meta_path = os.path.join(app_dir, 'app.json')
            compose_path = os.path.join(app_dir, 'docker-compose.yaml')
            if not os.path.isdir(app_dir) or not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                if not meta.get('name') or not meta.get('port'):
                    raise ValueError("Missing 'name' or 'port' in app.json")
            except Exception as e:
                errs.append(f"{entry}: {e}")
                continue
            dest = os.path.join(apps_dir, entry)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(app_dir, dest)
            imported += 1

        return imported, '; '.join(errs) if errs else ''
    except Exception as e:
        return 0, str(e)


def get_app_files(app_dir):
    files = []
    if not os.path.isdir(app_dir):
        return files
    for entry in sorted(os.listdir(app_dir)):
        entry_path = os.path.join(app_dir, entry)
        if os.path.isfile(entry_path):
            try:
                with open(entry_path) as f:
                    content = f.read()
            except Exception:
                content = ''
            files.append({
                'name': entry,
                'path': entry_path,
                'content': content,
                'is_dir': False,
            })
        elif os.path.isdir(entry_path):
            files.append({
                'name': entry,
                'path': entry_path,
                'content': '',
                'is_dir': True,
            })
    return files


def get_volume_map():
    db = get_db()
    rows = db.execute('SELECT name, path FROM virtual_volumes').fetchall()
    return {r[0]: r[1] for r in rows}


def substitute_volumes(content, volume_map):
    if not volume_map:
        return content
    try:
        return StringTemplate(content).safe_substitute(**volume_map)
    except Exception:
        return content


def find_volume_refs(content):
    refs = set()
    for m in re.finditer(r'\$([A-Z_][A-Z0-9_]*)', content):
        refs.add(m.group(1))
    return sorted(refs)


# ─── Sources ──────────────────────────────────────────────

def get_sources():
    db = get_db()
    rows = db.execute('SELECT id, url, priority, last_status, last_error, last_count, created_at, updated_at FROM app_sources ORDER BY priority ASC, id ASC').fetchall()
    return [{
        'id': r[0], 'url': r[1], 'priority': r[2],
        'last_status': r[3], 'last_error': r[4], 'last_count': r[5],
        'created_at': str(r[6]) if r[6] else '', 'updated_at': str(r[7]) if r[7] else ''
    } for r in rows]


def save_source(url, status='added', count=0, error=''):
    db = get_db()
    existing = db.execute('SELECT id, priority FROM app_sources WHERE url = ?', [url]).fetchone()
    if existing:
        db.execute('''
            UPDATE app_sources SET last_status = ?, last_error = ?, last_count = ?, updated_at = CURRENT_TIMESTAMP WHERE url = ?
        ''', [status, error, count, url])
    else:
        max_pri = db.execute('SELECT COALESCE(MAX(priority), 0) FROM app_sources').fetchone()[0]
        db.execute('''
            INSERT INTO app_sources (id, url, priority, last_status, last_error, last_count)
            VALUES (nextval('app_source_id_seq'), ?, ?, ?, ?, ?)
        ''', [url, max_pri + 1, status, error, count])


# ─── App Store ─────────────────────────────────────────────

@apps_bp.route('/apps')
@login_required
def list_apps():
    repo_url = request.args.get('repo_url')
    if repo_url:
        imported, errors = import_apps_from_source(repo_url)
        if imported:
            save_source(repo_url, 'success', imported)
            flash(f"Imported {imported} app(s) from source", "success")
        elif errors:
            save_source(repo_url, 'error', 0, errors)
            flash(f"Import errors: {errors}", "error")
        else:
            flash("No apps found. Ensure each app is in a subfolder with app.json.", "info")
    all_apps = get_local_apps()
    sources = get_sources()
    return render_template('apps.html', apps=all_apps, sources=sources, repo_url=repo_url)


@apps_bp.route('/sources/<int:source_id>/remove', methods=['POST'])
@login_required
def source_remove(source_id):
    db = get_db()
    row = db.execute('SELECT url FROM app_sources WHERE id = ?', [source_id]).fetchone()
    if row:
        repo_dir = _repo_dir(row[0])
        if os.path.isdir(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)
    db.execute('DELETE FROM app_sources WHERE id = ?', [source_id])
    flash("Source removed from list.", "success")
    return redirect(url_for('apps.list_apps'))


@apps_bp.route('/sources/<int:source_id>/move/<direction>', methods=['POST'])
@login_required
def source_move(source_id, direction):
    if direction not in ('up', 'down'):
        return redirect(url_for('apps.list_apps'))
    db = get_db()
    cur = db.execute('SELECT id, priority FROM app_sources WHERE id = ?', [source_id]).fetchone()
    if not cur:
        flash("Source not found.", "error")
        return redirect(url_for('apps.list_apps'))
    cur_id, cur_pri = cur
    step = -1 if direction == 'up' else 1
    neighbor = db.execute(
        'SELECT id, priority FROM app_sources WHERE priority = ?', [cur_pri + step]
    ).fetchone()
    if neighbor:
        db.execute('UPDATE app_sources SET priority = ? WHERE id = ?', [cur_pri, neighbor[0]])
        db.execute('UPDATE app_sources SET priority = ? WHERE id = ?', [cur_pri + step, cur_id])
    return redirect(url_for('apps.list_apps'))


@apps_bp.route('/sources/refresh-all', methods=['POST'])
@login_required
def refresh_all():
    sources = get_sources()
    results = []
    for src in sources:
        imported, errors = import_apps_from_source(src['url'])
        if imported:
            save_source(src['url'], 'success', imported)
            results.append(f"{src['url']}: {imported} app(s)")
        elif errors:
            save_source(src['url'], 'error', 0, errors)
            results.append(f"{src['url']}: ERROR — {errors}")
        else:
            results.append(f"{src['url']}: no new apps")
    flash("Refresh complete. " + " | ".join(results), "success" if not any('ERROR' in r for r in results) else "error")
    return redirect(url_for('apps.list_apps'))


@apps_bp.route('/apps/<name>')
@login_required
def app_detail(name):
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
        flash(f"Error loading app metadata: {e}", "error")
        return redirect(url_for('apps.list_apps'))

    app_files = get_app_files(app_dir)
    deploy_source = os.path.join(current_app.root_path, 'deployments', name, 'docker-compose.source.yaml')
    compose_content = ''
    if os.path.isfile(deploy_source):
        with open(deploy_source) as f:
            compose_content = f.read()
    else:
        compose_path = os.path.join(app_dir, 'docker-compose.yaml')
        if os.path.isfile(compose_path):
            with open(compose_path) as f:
                compose_content = f.read()

    volume_map = get_volume_map()
    volume_refs = find_volume_refs(compose_content)
    resolved_compose = substitute_volumes(compose_content, volume_map)

    domain = ''
    deploy_dir = os.path.join(current_app.root_path, 'deployments', name)
    if os.path.isdir(deploy_dir):
        db = get_db()
        row = db.execute('SELECT domain FROM deployed_apps WHERE folder = ?', [name]).fetchone()
        if row:
            domain = row[0] or ''

    db = get_db()
    sd_rows = db.execute('SELECT id, path FROM shared_dirs ORDER BY id DESC').fetchall()
    shared_dirs = [{'id': r[0], 'path': r[1]} for r in sd_rows]
    vol_rows = db.execute('SELECT id, name, path FROM virtual_volumes ORDER BY id DESC').fetchall()
    volumes = [{'id': r[0], 'name': r[1], 'path': r[2]} for r in vol_rows]

    return render_template('app_detail.html',
                           meta=meta,
                           name=name,
                           compose=compose_content,
                           resolved_compose=resolved_compose,
                           app_files=app_files,
                           volume_refs=volume_refs,
                           shared_dirs=shared_dirs,
                           volumes=volumes,
                           volume_map_json=json.dumps(volume_map),
                           domain=domain,
                           main_domain=os.environ.get('CADDY_DOMAIN', '').strip())


def _async_deploy(app_dir, deploy_dir, name, meta, domain):
    caddy_path = os.path.join(app_dir, 'Caddyfile')
    caddy_deploy = os.path.join(deploy_dir, 'Caddyfile')
    if os.path.isfile(caddy_path):
        with open(caddy_path) as f:
            caddy_content = f.read()
        with open(caddy_deploy, 'w') as f:
            f.write(caddy_content)

    main_domain = os.environ.get('CADDY_DOMAIN', '').strip()
    port = meta.get('port', 0)
    caddyfile = os.path.join(current_app.root_path, 'Caddyfile')
    safe_name = name.lower().replace('_', '-').replace(' ', '-')

    if port and os.path.isfile(caddyfile):
        apps_d = os.path.join(current_app.root_path, 'apps.d')

        if domain:
            sites_d = os.path.join(apps_d, 'sites')
            os.makedirs(sites_d, exist_ok=True)
            entry = f'\n{domain} {{\n    tls internal\n    reverse_proxy localhost:{port}\n}}\n'
            app_caddy = os.path.join(sites_d, f'{safe_name}.caddy')
            if not os.path.isfile(app_caddy) or open(app_caddy).read() != entry:
                with open(app_caddy, 'w') as f:
                    f.write(entry)

        if main_domain and not domain:
            paths_d = os.path.join(apps_d, 'paths')
            os.makedirs(paths_d, exist_ok=True)
            entry = f'handle_path /{safe_name}/* {{\n    reverse_proxy localhost:{port}\n}}\n'
            app_caddy = os.path.join(paths_d, f'{safe_name}.caddy')
            if not os.path.isfile(app_caddy) or open(app_caddy).read() != entry:
                with open(app_caddy, 'w') as f:
                    f.write(entry)

        try:
            caddy_bin = os.path.join(current_app.root_path, '.pixi', 'envs', 'default', 'bin', 'caddy')
            subprocess.run([caddy_bin, 'reload', '--config', caddyfile],
                           capture_output=True, text=True, timeout=10)
        except Exception:
            pass

    try:
        payload = {'folder': name}
        http_requests.post(f'{AGENT_URL}/api/deploy', json=payload, timeout=300)
    except Exception:
        pass


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
    domain = request.form.get('domain', '').strip()
    main_domain = os.environ.get('CADDY_DOMAIN', '').strip()
    port = meta.get('port', 0)

    effective_domain = domain
    if not effective_domain and main_domain and port:
        subdomain = name.lower().replace('_', '-').replace(' ', '-')
        effective_domain = f'{main_domain}/{subdomain}'

    deploy_dir = os.path.join(current_app.root_path, 'deployments', name)
    os.makedirs(deploy_dir, exist_ok=True)
    compose_path = os.path.join(deploy_dir, 'docker-compose.yaml')
    if compose_edited:
        compose_content = compose_edited
    else:
        template_path = os.path.join(app_dir, 'docker-compose.yaml')
        if os.path.isfile(template_path):
            with open(template_path) as f:
                compose_content = f.read()
        else:
            compose_content = ''
    if compose_content:
        with open(os.path.join(deploy_dir, 'docker-compose.source.yaml'), 'w') as f:
            f.write(compose_content)
        volume_map = get_volume_map()
        resolved = substitute_volumes(compose_content, volume_map)
        if domain:
            resolved = StringTemplate(resolved).safe_substitute(DOMAIN=domain)
        with open(compose_path, 'w') as f:
            f.write(resolved)

    db = get_db()
    db.execute('''
        INSERT INTO deployed_apps (id, name, folder, port, status, domain)
        VALUES (nextval('deployed_app_id_seq'), ?, ?, ?, 'deploying', ?)
        ON CONFLICT (name) DO UPDATE SET status = 'deploying', port = ?, domain = ?, updated_at = now()
    ''', [meta['name'], name, port, effective_domain or '', port, effective_domain or ''])

    t = threading.Thread(target=_async_deploy, args=(app_dir, deploy_dir, name, meta, domain), daemon=True)
    t.start()

    flash(f"{meta['name']} deploying...", "success")
    return redirect(url_for('apps.deployed_list'))


# ─── Deployed Apps ──────────────────────────────────────────

@apps_bp.route('/deployed')
@login_required
def deployed_list():
    db = get_db()
    rows = db.execute('SELECT id, name, folder, port, status, domain, created_at, updated_at FROM deployed_apps ORDER BY id DESC').fetchall()

    live_states = {}
    host_data_path = os.path.join(current_app.root_path, '_host_data.json')
    try:
        with open(host_data_path) as f:
            host_data = json.load(f)
        for c in host_data.get('containers', []):
            project = c.get('Labels', {}).get('com.docker.compose.project', '')
            if project.startswith('nasypeasy-'):
                folder = project[len('nasypeasy-'):]
                live_states[folder] = c.get('State', '')
    except Exception:
        pass

    deployed = []
    for r in rows:
        app = {
            'id': r[0], 'name': r[1], 'folder': r[2],
            'port': r[3], 'status': r[4], 'domain': r[5] or '',
            'created_at': r[6], 'updated_at': r[7]
        }
        if app['folder'] in live_states:
            app['status'] = live_states[app['folder']]
        deployed.append(app)
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
            db.execute('UPDATE deployed_apps SET status = ? WHERE folder = ?', ['stopped', name])
            flash("App stopped", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('apps.deployed_list'))


@apps_bp.route('/deployed/<name>/up', methods=['POST'])
@login_required
def deployed_up(name):
    try:
        resp = http_requests.post(f'{AGENT_URL}/api/deployed/{name}/up', timeout=30)
        if resp.status_code != 200:
            flash(f"Error starting app: {resp.text}", "error")
        else:
            db = get_db()
            db.execute('UPDATE deployed_apps SET status = ? WHERE folder = ?', ['running', name])
            flash("App started", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('apps.deployed_list'))


@apps_bp.route('/deployed/<name>/delete', methods=['POST'])
@login_required
def deployed_delete(name):
    remove_volumes = request.form.get('remove_volumes') == '1'
    try:
        resp = http_requests.post(
            f'{AGENT_URL}/api/deployed/{name}/delete',
            json={'remove_volumes': remove_volumes},
            timeout=30
        )
        if resp.status_code != 200:
            flash(f"Error deleting app: {resp.text}", "error")
        else:
            db = get_db()
            db.execute('DELETE FROM deployed_apps WHERE folder = ?', [name])
            deploy_dir = os.path.join(current_app.root_path, 'deployments', name)
            if os.path.isdir(deploy_dir):
                shutil.rmtree(deploy_dir, ignore_errors=True)

            safe_name = name.lower().replace('_', '-').replace(' ', '-')
            for sub in ('paths', 'sites'):
                f = os.path.join(current_app.root_path, 'apps.d', sub, f'{safe_name}.caddy')
                if os.path.isfile(f):
                    os.remove(f)

            caddyfile = os.path.join(current_app.root_path, 'Caddyfile')
            if os.path.isfile(caddyfile):
                try:
                    caddy_bin = os.path.join(current_app.root_path, '.pixi', 'envs', 'default', 'bin', 'caddy')
                    subprocess.run([caddy_bin, 'reload', '--config', caddyfile],
                                   capture_output=True, text=True, timeout=10)
                except Exception:
                    pass

            flash("App deleted", "success")
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


# ─── Shared Directories ───────────────────────────────────

@apps_bp.route('/shared-dirs')
@login_required
def shared_dir_list():
    db = get_db()
    rows = db.execute('SELECT id, path, created_at FROM shared_dirs ORDER BY id DESC').fetchall()
    dirs = [{'id': r[0], 'path': r[1], 'created_at': str(r[2])} for r in rows]
    return jsonify(dirs)


@apps_bp.route('/shared-dirs/add', methods=['POST'])
@login_required
def shared_dir_add():
    path = request.form.get('path', '').strip()
    if not path:
        flash("Path is required.", "error")
        return redirect(url_for('apps.volume_list'))
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            flash(f"Cannot create directory: {e}", "error")
            return redirect(url_for('apps.volume_list'))
    try:
        db = get_db()
        db.execute(
            'INSERT INTO shared_dirs (id, path) VALUES (nextval(\'shared_dir_id_seq\'), ?)',
            [path]
        )
        flash(f"Shared directory added: {path}", "success")
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            flash("Shared directory already exists.", "error")
        else:
            flash(f"Error: {e}", "error")
    return redirect(url_for('apps.volume_list'))


@apps_bp.route('/shared-dirs/<int:id>/delete', methods=['POST'])
@login_required
def shared_dir_delete(id):
    try:
        db = get_db()
        db.execute('DELETE FROM shared_dirs WHERE id = ?', [id])
        flash("Shared directory removed.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for('apps.volume_list'))


# ─── Virtual Volumes ──────────────────────────────────────

def fmt_bytes(b):
    if b < 1024:
        return f'{b} B'
    elif b < 1024 ** 2:
        return f'{b / 1024:.1f} KB'
    elif b < 1024 ** 3:
        return f'{b / 1024 ** 2:.1f} MB'
    else:
        return f'{b / 1024 ** 3:.2f} GB'


def dir_size(path):
    try:
        r = subprocess.run(['du', '-sb', path], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            b = int(r.stdout.split()[0])
            return b, fmt_bytes(b)
    except Exception:
        pass
    return 0, '0 B'


@apps_bp.route('/volumes')
@login_required
def volume_list():
    db = get_db()

    sd_rows = db.execute('SELECT id, path, created_at FROM shared_dirs ORDER BY id DESC').fetchall()
    shared_dirs = []
    for r in sd_rows:
        raw, formatted = dir_size(r[1]) if os.path.isdir(r[1]) else (0, '0 B')
        shared_dirs.append({'id': r[0], 'path': r[1], 'created_at': str(r[2]), 'size_bytes': raw, 'size': formatted})

    vol_rows = db.execute('''
        SELECT v.id, v.name, v.path, v.created_at, v.shared_dir_id
        FROM virtual_volumes v ORDER BY v.id DESC
    ''').fetchall()
    volumes = []
    for r in vol_rows:
        valid = os.path.isdir(r[2]) if r[2] else False
        raw, formatted = dir_size(r[2]) if valid else (0, '0 B')
        volumes.append({
            'id': r[0], 'name': r[1], 'path': r[2],
            'created_at': r[3], 'shared_dir_id': r[4], 'valid': valid,
            'size_bytes': raw, 'size': formatted
        })

    mount_path = '/'
    if shared_dirs:
        mount_path = shared_dirs[0]['path']
        while not os.path.ismount(mount_path) and mount_path != '/':
            mount_path = os.path.dirname(mount_path)
    try:
        du = shutil.disk_usage(mount_path)
        disk_total = du.total
        disk_used = du.used
        disk_free = du.free
        disk_percent = round(du.used / du.total * 100, 1)
    except Exception:
        disk_total = disk_used = disk_free = disk_percent = 0

    return render_template('volumes.html', volumes=volumes, shared_dirs=shared_dirs,
                           disk_total=disk_total, disk_used=disk_used,
                           disk_free=disk_free, disk_percent=disk_percent,
                           fmt_bytes=fmt_bytes)


@apps_bp.route('/volumes/add', methods=['POST'])
@login_required
def volume_add():
    name = request.form.get('name', '').strip().upper()
    shared_dir_id = request.form.get('shared_dir_id', '').strip()

    if not name or not shared_dir_id:
        flash("Volume name and shared directory are required.", "error")
        return redirect(url_for('apps.volume_list'))
    if not re.match(r'^[A-Z_][A-Z0-9_]*$', name):
        flash("Volume name must be uppercase alphanumeric (e.g. DATA, MEDIA_PATH).", "error")
        return redirect(url_for('apps.volume_list'))

    try:
        shared_dir_id = int(shared_dir_id)
    except ValueError:
        flash("Invalid shared directory.", "error")
        return redirect(url_for('apps.volume_list'))

    db = get_db()
    sd = db.execute('SELECT id, path FROM shared_dirs WHERE id = ?', [shared_dir_id]).fetchone()
    if not sd:
        flash("Shared directory not found.", "error")
        return redirect(url_for('apps.volume_list'))

    parent_path = sd[1]
    vol_path = os.path.join(parent_path, name)

    try:
        os.makedirs(vol_path, exist_ok=True)
        os.chmod(vol_path, 0o777)
    except Exception as e:
        flash(f"Cannot create volume directory: {e}", "error")
        return redirect(url_for('apps.volume_list'))

    try:
        db.execute('''
            INSERT INTO virtual_volumes (id, name, path, shared_dir_id)
            VALUES (nextval('virtual_volume_id_seq'), ?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET path = ?, shared_dir_id = ?, updated_at = now()
        ''', [name, vol_path, shared_dir_id, vol_path, shared_dir_id])
        flash(f"Volume '{name}' created at {vol_path}", "success")
    except Exception as e:
        flash(f"Error adding volume: {e}", "error")

    return redirect(url_for('apps.volume_list'))


@apps_bp.route('/volumes/<int:id>/delete', methods=['POST'])
@login_required
def volume_delete(id):
    try:
        db = get_db()
        vol = db.execute('SELECT path FROM virtual_volumes WHERE id = ?', [id]).fetchone()
        if vol and os.path.isdir(vol[0]):
            try:
                os.rmdir(vol[0])
            except OSError:
                pass
        db.execute('DELETE FROM virtual_volumes WHERE id = ?', [id])
        flash("Volume deleted.", "success")
    except Exception as e:
        flash(f"Error deleting volume: {e}", "error")
    return redirect(url_for('apps.volume_list'))
