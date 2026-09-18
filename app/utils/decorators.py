"""Authorization decorators for API routes."""
from functools import wraps

from flask import abort
from flask_login import current_user as login_current_user

from app.utils.permissions import is_pro


def pro_required(fn):
    """Abort with 403 unless the current user is on the 'pro' plan."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_pro(login_current_user):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper