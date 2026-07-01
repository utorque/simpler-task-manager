"""Server-rendered pages + session auth (login/logout)."""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('pages.login'))
    return render_template('index.html')


@pages_bp.route('/notes')
def notes_page():
    if not session.get('authenticated'):
        return redirect(url_for('pages.login'))
    return render_template('notes.html')


@pages_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.json.get('password')
        if password == current_app.config['APP_PASSWORD']:
            session['authenticated'] = True
            return jsonify({'success': True})
        return jsonify({'error': 'Invalid password'}), 401
    return render_template('login.html')


@pages_bp.route('/logout', methods=['POST'])
def logout():
    session.pop('authenticated', None)
    return jsonify({'success': True})
