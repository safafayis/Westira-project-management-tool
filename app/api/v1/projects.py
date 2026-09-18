from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from werkzeug.exceptions import abort

from app.services import project_service
from swagger_spec import _err, _ok, _p, _q, api_doc

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')


@projects_bp.get('')
@login_required
@api_doc('List projects', ['Projects'],
    params=[
        _q('status', {'type': 'string'}, 'Filter by project status'),
        _q('q',      {'type': 'string'}, 'Search project name or key'),
    ],
    resp={'200': {'description': 'Array of projects with members',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/Project'}}}}}})
def list_projects():
    return jsonify(project_service.list_projects(
        request.args.get('status'),
        request.args.get('q', '').strip().lower()))


@projects_bp.get('/<int:project_id>')
@login_required
@api_doc('Get project', ['Projects'],
    params=[_p('project_id', {'type': 'integer'}, 'Project ID')],
    resp={'200': _ok('#/components/schemas/Project'), **_err([404])})
def get_project(project_id):
    return jsonify(project_service.get_project(project_id))


@projects_bp.delete('/<int:project_id>')
@login_required
@api_doc('Delete project', ['Projects'],
    params=[_p('project_id', {'type': 'integer'}, 'Project ID')],
    resp={'200': _ok(), **_err([403, 404])})
def delete_project(project_id):
    from app.models import Project
    obj = Project.query.get_or_404(project_id)
    if current_user.plan != 'pro' and current_user.id != obj.lead_id:
        abort(403)
    return jsonify(project_service.delete_project(project_id))


@projects_bp.get('/<int:project_id>/members')
@login_required
@api_doc('List project members', ['Projects'],
    params=[_p('project_id', {'type': 'integer'}, 'Project ID')],
    resp={'200': {'description': 'Array of member users',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/User'}}}}}})
def project_members(project_id):
    return jsonify(project_service.project_members(project_id))


@projects_bp.post('/<int:project_id>/members')
@login_required
@api_doc('Add project member', ['Projects'],
    params=[_p('project_id', {'type': 'integer'}, 'Project ID')],
    req={'type': 'object', 'required': ['user_id'],
         'properties': {'user_id': {'type': 'integer'}}},
    resp={'201': _ok(None, 'Member added'), **_err([400, 404, 409])})
def add_member(project_id):
    data = request.get_json(silent=True) or {}
    resp, status = project_service.add_member(project_id, data.get('user_id'))
    return jsonify(resp), status


@projects_bp.delete('/<int:project_id>/members/<int:user_id>')
@login_required
@api_doc('Remove project member', ['Projects'],
    params=[
        _p('project_id', {'type': 'integer'}, 'Project ID'),
        _p('user_id',    {'type': 'integer'}, 'User ID'),
    ],
    resp={'200': _ok(), **_err([404])})
def remove_member(project_id, user_id):
    return jsonify(project_service.remove_member(project_id, user_id))


@projects_bp.post('')
@login_required
@api_doc('Create project', ['Projects'],
    req={'type': 'object',
         'required': ['name', 'start_date', 'target_date', 'manager'],
         'properties': {
             'name':           {'type': 'string', 'maxLength': 160},
             'description':    {'type': 'string'},
             'start_date':     {'type': 'string'},
             'target_date':    {'type': 'string', 'description': 'Alias: due_date'},
             'manager':        {'type': 'string', 'description': 'User ID or initials'},
             'manager_id':     {'type': 'integer'},
             'assignees':      {'type': 'array', 'items': {'type': 'integer'}, 'description': 'Team member user IDs'},
             'team_members':   {'type': 'array', 'items': {'type': 'integer'}, 'description': 'Alias for assignees'},
         }},
    resp={'201': _ok('#/components/schemas/Project', 'Created'), **_err([400])})
def create_project():
    data = request.get_json(silent=True) or {}
    resp, status = project_service.create_project(data, current_user)
    return jsonify(resp), status


@projects_bp.patch('/<int:project_id>')
@login_required
@api_doc('Update project', ['Projects'],
    params=[_p('project_id', {'type': 'integer'}, 'Project ID')],
    req={'type': 'object',
         'description': 'Any subset of project fields',
         'properties': {
             'name':         {'type': 'string'},
             'description':  {'type': 'string'},
             'start_date':   {'type': 'string'},
             'target_date':  {'type': 'string'},
             'due_date':     {'type': 'string'},
             'priority':     {'type': 'string'},
             'status':       {'type': 'string'},
         }},
    resp={'200': _ok('#/components/schemas/Project'), **_err([400, 404])})
def update_project(project_id):
    data = request.get_json(silent=True) or {}
    resp, status = project_service.update_project(project_id, data, current_user)
    return jsonify(resp), status