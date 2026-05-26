from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from db import get_db

auth_bp = Blueprint('auth', __name__)
login_manager = LoginManager()


@login_manager.unauthorized_handler
def unauthorized():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': 'Unauthorized'}), 401
    return redirect(url_for('auth.login'))

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    result = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
    if result:
        return User(id=result[0], username=result[1])
    return None

def init_auth(app):
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    app.register_blueprint(auth_bp)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db()
        user_record = conn.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()

        if user_record and check_password_hash(user_record[2], password):
            user = User(id=user_record[0], username=user_record[1])
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
