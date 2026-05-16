from flask import Flask, render_template, request, redirect, url_for, flash
import os
from auth import init_auth
from apps import apps_bp
from utils import get_podman_containers, get_tailscale_status, is_cockpit_reachable
from flask_login import login_required
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
# In production, this should be an environment variable. Using a static fallback for simplicity.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "nasypeasy-dev-secret-key-12345")
csrf = CSRFProtect(app)

init_auth(app)
app.register_blueprint(apps_bp)

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    containers = get_podman_containers()
    ts_status = get_tailscale_status()
    cockpit_reachable = is_cockpit_reachable()
    return render_template('dashboard.html', containers=containers, ts_status=ts_status, cockpit_reachable=cockpit_reachable)

if __name__ == '__main__':
    from db import init_db
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
