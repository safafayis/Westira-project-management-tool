from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.services import sprint_service
from swagger_spec import _err, _ok, _p, _q, api_doc

sprints_bp = Blueprint('sprints', __name__, url_prefix='/sprints')


@sprints_bp.get('')
@login_required
@api_doc('List sprints', ['Sprints'],
    params=[_q('project', {'type': 'string'}, 'Project key')],
    resp={'200': {'description': 'Array of sprints with tasks',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/Sprint'}}}}}})
def list_sprints():
    return jsonify(sprint_service.list_sprints(request.args.get('project')))


@sprints_bp.get('/<int:sprint_id>')
@login_required
@api_doc('Get sprint', ['Sprints'],
    params=[_p('sprint_id', {'type': 'integer'}, 'Sprint ID')],
    resp={'200': _ok('#/components/schemas/Sprint'), **_err([404])})
def get_sprint(sprint_id):
    return jsonify(sprint_service.get_sprint(sprint_id))


@sprints_bp.post('')
@login_required
@api_doc('Create sprint', ['Sprints'],
    req={'type': 'object',
         'required': ['project', 'name', 'start_date', 'end_date', 'goal'],
         'properties': {
             'project':      {'type': 'string', 'description': 'Project key'},
             'name':         {'type': 'string', 'maxLength': 80},
             'start_date':   {'type': 'string'},
             'end_date':     {'type': 'string', 'description': 'Alias: target_date'},
             'goal':         {'type': 'string'},
             'description':  {'type': 'string'},
             'task_ids':     {'type': 'array', 'items': {'type': 'integer'}, 'description': 'Alias: tasks'},
         }},
    resp={'201': _ok('#/components/schemas/Sprint', 'Created'),
          **_err([400, 409])})
def create_sprint():
    data = request.get_json(silent=True) or {}
    resp, status = sprint_service.create_sprint(data)
    return jsonify(resp), status


@sprints_bp.patch('/<int:sprint_id>')
@login_required
@api_doc('Update sprint', ['Sprints'],
    params=[_p('sprint_id', {'type': 'integer'}, 'Sprint ID')],
    req={'type': 'object',
         'description': 'Any subset of sprint fields',
         'properties': {
             'project':      {'type': 'string', 'description': 'Project key'},
             'name':         {'type': 'string'},
             'start_date':   {'type': 'string'},
             'end_date':     {'type': 'string'},
             'goal':         {'type': 'string'},
             'description':  {'type': 'string'},
             'task_ids':     {'type': 'array', 'items': {'type': 'integer'}},
         }},
    resp={'200': _ok('#/components/schemas/Sprint'), **_err([400, 409])})
def update_sprint(sprint_id):
    data = request.get_json(silent=True) or {}
    resp, status = sprint_service.update_sprint(sprint_id, data)
    return jsonify(resp), status


@sprints_bp.post('/<int:sprint_id>/start')
@login_required
@api_doc('Start sprint', ['Sprints'],
    params=[_p('sprint_id', {'type': 'integer'}, 'Sprint ID')],
    resp={'200': _ok('#/components/schemas/Sprint'), **_err([409])})
def start_sprint(sprint_id):
    resp, status = sprint_service.start_sprint(sprint_id, current_user)
    return jsonify(resp), status


@sprints_bp.post('/<int:sprint_id>/complete')
@login_required
@api_doc('Complete sprint', ['Sprints'],
    params=[_p('sprint_id', {'type': 'integer'}, 'Sprint ID')],
    req={'type': 'object',
         'description': 'Provide incomplete_action when issues remain incomplete',
         'properties': {
             'incomplete_action': {'type': 'string', 'enum': ['backlog', 'next', 'keep'],
                                   'description': 'How to handle incomplete issues: move to backlog, next sprint, or keep'},
         }},
    resp={'200': _ok('#/components/schemas/Sprint'), **_err([409])})
def complete_sprint(sprint_id):
    data = request.get_json(silent=True) or {}
    resp, status = sprint_service.complete_sprint(sprint_id, data, current_user)
    return jsonify(resp), status