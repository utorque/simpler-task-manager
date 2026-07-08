"""App factory. All routes live in per-domain blueprints under `routes/`.

`app = create_app()` is kept at module level so `python src/app.py`, the
Docker entrypoint, and the test harness (`from app import app`) keep working.
"""

from flask import Flask

from config import Config
from models import db
from seeding import seed_default_spaces


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    db.init_app(app)

    from routes.pages import pages_bp
    from routes.tasks import tasks_bp
    from routes.spaces import spaces_bp
    from routes.notes import notes_bp
    from routes.calendar_sources import calendar_sources_bp
    from routes.schedule import schedule_bp
    from routes.mailboxes import mailboxes_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(spaces_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(calendar_sources_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(mailboxes_bp)

    with app.app_context():
        db.create_all()
        seed_default_spaces()

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=53000, debug=True)
