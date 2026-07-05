"""Server-rendered pages + session auth (login/logout)."""

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('pages.login'))
    # Hermes iframe src: same-origin proxy (/hermes-ui/, no reverse-proxy
    # changes needed) when the compose-internal URL is set; else a directly
    # reachable external webui URL; else no Hermes tab at all.
    if current_app.config.get('HERMES_WEBUI_INTERNAL_URL'):
        hermes_src = '/hermes-ui/'
    else:
        hermes_src = current_app.config.get('HERMES_WEBUI_URL')
    return render_template('index.html', hermes_webui_url=hermes_src)


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
