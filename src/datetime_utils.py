"""Datetime parsing shared by all route blueprints."""

from datetime import datetime


def parse_iso_datetime(iso_string):
    """Parse ISO datetime string in local timezone format.

    Handles both '2025-12-16T12:00:00' (local, current frontend format) and
    '2025-12-16T12:00:00.000Z' (legacy UTC). Values are stored naive.
    """
    if not iso_string:
        return None
    if iso_string.endswith('Z'):
        iso_string = iso_string[:-1] + '+00:00'
        return datetime.fromisoformat(iso_string).replace(tzinfo=None)
    return datetime.fromisoformat(iso_string)
