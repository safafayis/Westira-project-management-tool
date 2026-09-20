from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services import team_service
from app.utils.decorators import team_manager_required
from swagger_spec import _err, _ok, _p, _q, api_doc

users_bp = Blueprint('users', __name__, url_prefix='/users')
team_bp = Blueprint('team_roles', __name__, url_prefix='/team')


@users_bp.get('')
@login_required
@api_doc('List users', ['Users & Team'],
    params=[
        _q('q',      {'type': 'string'}, 'Search name, email, team, role'),
        _q('plan',   {'type': 'string', 'enum': ['pro', 'plus', 'lite']}),
        _q('role',   {'type': 'string'}, 'Filter by role'),
        _q('team',   {'type': 'string'}, 'Filter by team'),
        _q('status', {'type': 'string', 'enum': ['online', 'offline']}, 'Online status filter'),
    ],
    resp={'200': {'description': 'Array of users',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/User'}}}}}})
def list_users():
    return jsonify(team_service.list_users(request.args))


@users_bp.get('/<int:user_id>')
@login_required
@api_doc('Get user', ['Users & Team'],
    params=[_p('user_id', {'type': 'integer'}, 'User ID')],
    resp={'200': _ok('#/components/schemas/User'), **_err([404])})
def get_user(user_id):
    return jsonify(team_service.get_user(user_id))


@users_bp.post('')
@login_required
@team_manager_required
@api_doc('Create user (Pro Project Manager only)', ['Users & Team'],
    desc='Only a Pro Project Manager can add team members. Password is optional; '
         'when omitted a random credential is generated.',
    req={'type': 'object',
         'required': ['name', 'email', 'role'],
         'properties': {
             'name':     {'type': 'string'},
             'email':    {'type': 'string', 'format': 'email'},
             'password': {'type': 'string', 'description': 'Optional; auto-generated when omitted'},
             'role':     {'type': 'string'},
             'plan':     {'type': 'string', 'enum': ['pro', 'plus', 'lite'], 'default': 'lite'},
             'team':     {'type': 'string', 'default': 'General'},
             'status':   {'type': 'string', 'enum': ['Active', 'Inactive'], 'default': 'Active'},
         }},
    resp={'201': _ok('#/components/schemas/User', 'Created'), **_err([400, 403, 409])})
def create_user():
    data = request.get_json(silent=True) or {}
    resp, status = team_service.create_user(data)
    return jsonify(resp), status


@users_bp.put('/<int:user_id>')
@login_required
@team_manager_required
@api_doc('Update user (Pro Project Manager only)', ['Users & Team'],
    desc='Only a Pro Project Manager can edit or activate/deactivate team members.',
    params=[_p('user_id', {'type': 'integer'}, 'User ID')],
    req={'type': 'object',
         'description': 'Any subset of user fields',
         'properties': {
             'name':     {'type': 'string'},
             'email':    {'type': 'string', 'format': 'email'},
             'role':     {'type': 'string'},
             'team':     {'type': 'string'},
             'plan':     {'type': 'string'},
             'status':   {'type': 'string', 'enum': ['Active', 'Inactive']},
             'capacity': {'type': 'integer'},
             'color':    {'type': 'string'},
         }},
    resp={'200': _ok('#/components/schemas/User'), **_err([400, 403, 404, 409])})
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    resp, status = team_service.update_user(user_id, data)
    return jsonify(resp), status


@users_bp.delete('/<int:user_id>')
@login_required
@team_manager_required
@api_doc('Delete user (Pro Project Manager only)', ['Users & Team'],
    params=[_p('user_id', {'type': 'integer'}, 'User ID')],
    req={'type': 'object',
         'required': ['confirm_email'],
         'properties': {'confirm_email': {'type': 'string', 'description': 'Must match user email to confirm'}}},
    resp={'200': _ok(), **_err([400, 403])})
def delete_user(user_id):
    if user_id == current_user.id:
        return jsonify({"ok": False, "error": "You cannot delete your own account."}), 400
    data = request.get_json(silent=True) or {}
    resp, status = team_service.delete_user(user_id, data)
    return jsonify(resp), status


@team_bp.get('/roles')
@login_required
@api_doc('List distinct team roles', ['Users & Team'],
    resp={'200': {'description': 'Array of {name, count}',
                  'content': {'application/json': {'schema': {
                      'type': 'array',
                      'items': {'type': 'object', 'properties': {
                          'name': {'type': 'string'}, 'count': {'type': 'integer'}}}}}}}})
def team_roles():
    """Distinct member roles for the Team page Role filter (driven by the DB)."""
    return jsonify(team_service.team_roles())