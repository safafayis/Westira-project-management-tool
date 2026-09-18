from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.services.auth_service import authenticate, register
from app.utils.helpers import user_dict
from swagger_spec import _err, _ok, api_doc

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.post('/login')
@api_doc('Log in', ['Authentication'],
         resp={'200': _ok('#/components/schemas/Auth'), **_err([401, 403])})
def login():
    """Authenticate a user and establish a session (JSON)."""
    if current_user.is_authenticated:
        return jsonify({'ok': True, 'redirect': url_for('dashboard')})
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    user = authenticate(email, password)
    if user:
        if user.status and user.status.lower() != 'active':
            return jsonify({'ok': False,
                            'error': 'This account has been deactivated. '
                                     'Contact your workspace administrator.'}), 403
        login_user(user)
        return jsonify({'ok': True, 'user': user_dict(user),
                        'redirect': url_for('dashboard')})
    return jsonify({'ok': False, 'error': 'Invalid email or password.'}), 401


@auth_bp.post('/register')
@api_doc('Register', ['Authentication'],
         resp={'201': _ok('#/components/schemas/Auth'), **_err([400, 401])})
def register():
    """Create a self-registered 'lite' account and log the user in."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'ok': False, 'error': 'Invalid JSON payload.'}), 400

    user, error = register(data)
    if error:
        return jsonify({'ok': False, 'error': error}), 400

    login_user(user)
    return jsonify({'ok': True, 'user': user_dict(user),
                    'redirect': url_for('dashboard')}), 201


@auth_bp.post('/logout')
@api_doc('Log out', ['Authentication'],          resp={'200': _ok(), **_err([401])})
@login_required
def logout():
    logout_user()
    return jsonify({'ok': True})


@auth_bp.get('/me')
@api_doc('Current user', ['Authentication'], resp={'200': _ok('#/components/schemas/User')})
@login_required
def me():
    return jsonify(user_dict(current_user))