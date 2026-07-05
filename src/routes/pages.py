"""Server-rendered pages + session auth (login/logout)."""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('pages.login'))
    return render_template(
        'index.html',
        hermes_webui_url=current_app.config.get('HERMES_WEBUI_URL'),
    )


@pages_bp.route('/notes')
def notes_page():
    # The workspace is one unified shell; /notes deep-links into its Notes view.
    if not session.get('authenticated'):
        return redirect(url_for('pages.login'))
    return redirect('/#notes')


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
