"""Default-space seeding, shared by the app factory and the test harness.

Previously duplicated between app.py's import-time block and
tests/conftest.py. Call inside an app context.
"""

from models import db, Space

DEFAULT_SPACES = [
    {
        'name': 'work',
        'description': 'Work-related tasks, meetings, and projects during office hours',
        'constraints': [
            {'day': 1, 'start': '09:00', 'end': '17:00'},
            {'day': 2, 'start': '09:00', 'end': '17:00'},
            {'day': 3, 'start': '09:00', 'end': '17:00'},
            {'day': 4, 'start': '09:00', 'end': '17:00'},
            {'day': 5, 'start': '09:00', 'end': '17:00'},
        ],
    },
    {
        'name': 'study',
        'description': 'Learning activities, courses, homework, and educational tasks',
        'constraints': [],
    },
    {
        'name': 'association',
        'description': 'Community group, club, or volunteer organization activities',
        'constraints': [{'day': 3, 'start': '18:00', 'end': '22:00'}],
    },
]


def seed_default_spaces():
    """Create the default spaces if the table is empty. Idempotent."""
    if Space.query.count() > 0:
        return
    for space_data in DEFAULT_SPACES:
        space = Space(name=space_data['name'], description=space_data['description'])
        space.set_time_constraints(space_data['constraints'])
        db.session.add(space)
    db.session.commit()
