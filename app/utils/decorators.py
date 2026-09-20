"""Authorization decorators for API routes."""
from functools import wraps

from flask import abort, jsonify, request
from flask_login import current_user as login_current_user

from app.utils.permissions import can_manage_team_members, is_pro


def _json_forbidden(message):
    """JSON 403 for API requests (mirrors the 401 unauthorized handler in
    app/__init__.py), so the frontend fetch helper can read the error body."""
    return jsonify({'ok': False, 'error': message}), 403


def pro_required(fn):
    """Reject with 403 unless the current user is on the 'pro' plan."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_pro(login_current_user):
            if request.path.startswith('/api/'):
                return _json_forbidden('You do not have permission to add team members.')
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def team_manager_required(fn):
    """Reject with 403 unless the current user can manage team members.

    ONLY Project Managers on the 'pro' plan may add/edit/activate/deactivate
    team members. This is the immutable backend authorization gate for the
    Team page mutation endpoints — it is never bypassable from the client.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not can_manage_team_members(login_current_user):
            if request.path.startswith('/api/'):
                return _json_forbidden('Only Pro Project Managers can manage team members.')
            abort(403)
        return fn(*args, **kwargs)
    return wrapper