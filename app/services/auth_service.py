"""Auth business logic: credential checks and self-registration."""
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models import User
from app.utils.helpers import ensure_settings_for_user


def authenticate(email, password):
    """Validate an email/password pair against the users table.

    Returns the matching active-capable user or None. The caller is still
    responsible for the activation-status check and creating the session.
    """
    email = (email or '').strip().lower()
    if not email or not password:
        return None
    user = User.query.filter_by(email=email).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return None
    return user


def register(data):
    """Create a new self-registered 'lite' user.

    Mirrors the old register endpoint validation + creation exactly.
    Returns (user, None) on success or (None, error_message) on failure.
    """
    data = data or {}
    name = (data.get('name') or '').strip() or ''
    email = ((data.get('email') or '') or '').strip().lower()
    password = data.get('password') or ''
    role = (data.get('role') or '') or ''
    team_raw = data.get('team')
    team = (team_raw or '').strip() or 'General'

    if not name or not email or not password or not role:
        return None, 'Please fill in all required fields.'

    if User.query.filter_by(email=email).first():
        return None, 'An account with that email already exists.'

    initials = ''.join(p[0] for p in name.split() if p)[:2].upper()
    if not initials:
        initials = 'XX'

    u = User(
        name=name,
        initials=initials,
        email=email,
        plan='lite',
        role=role,
        team=team,
        capacity=50,
        active_projects=0,
        current_tasks=0,
        color='#4f46e5',
        status='Active',
    )
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    ensure_settings_for_user(u)
    db.session.commit()
    return u, None