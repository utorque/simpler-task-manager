"""External calendar sources (ICS) and live external-event fetch."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from auth import login_required
from calendar_integration import fetch_external_events
from models import db, CalendarSource

calendar_sources_bp = Blueprint('calendar_sources', __name__)


@calendar_sources_bp.route('/api/calendar-sources', methods=['GET'])
@login_required
def get_calendar_sources():
    sources = CalendarSource.query.all()
    return jsonify([source.to_dict() for source in sources])


@calendar_sources_bp.route('/api/calendar-sources', methods=['POST'])
@login_required
def create_calendar_source():
    data = request.json

    source = CalendarSource(
        name=data['name'],
        ics_url=data['ics_url'],
        enabled=data.get('enabled', True)
    )

    db.session.add(source)
    db.session.commit()

    return jsonify(source.to_dict()), 201


@calendar_sources_bp.route('/api/calendar-sources/<int:source_id>', methods=['DELETE'])
@login_required
def delete_calendar_source(source_id):
    source = CalendarSource.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    return jsonify({'success': True})


@calendar_sources_bp.route('/api/external-events', methods=['GET'])
@login_required
def get_external_events():
    all_events = []
    sources = CalendarSource.query.filter_by(enabled=True).all()

    for source in sources:
        events = fetch_external_events(source.ics_url)
        # Convert datetime objects to ISO format strings for JSON serialization
        for event in events:
            if isinstance(event.get('start'), datetime):
                event['start'] = event['start'].isoformat()
            if isinstance(event.get('end'), datetime):
                event['end'] = event['end'].isoformat()
        all_events.extend(events)

    return jsonify(all_events)
