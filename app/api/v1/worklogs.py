"""Work log endpoints (Team Work Time).

Every endpoint is scoped by ``project_id`` on the backend: a request for one
project can never return another project's rows. Write operations derive the
actor from the session (never from the frontend) and enforce project
membership / ownership rules.
"""
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.services import worklog_service
from swagger_spec import _err, _ok, _p, _q, api_doc

worklogs_bp = Blueprint('worklogs', __name__, url_prefix='/worklogs')


def _actor():
    return current_user if current_user.is_authenticated else None


@worklogs_bp.get('/summary')
@api_doc('Project work time summary', ['Work Logs'],
    params=[
        _q('project_id', {'type': 'integer'}, 'Project ID', required=True),
    ],
    resp={'200': _ok('#/components/schemas/WorkTimeSummary'), **_err([401, 403, 404])})
def work_time_summary():
    if not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
    project_id = request.args.get('project_id', type=int)
    resp, status = worklog_service.summary(project_id, _actor())
    return jsonify(resp), status


@worklogs_bp.get('')
@api_doc('List project work logs', ['Work Logs'],
    params=[
        _q('project_id', {'type': 'integer'}, 'Project ID', required=True),
        _q('user_id',    {'type': 'integer'}, 'Filter by user ID'),
        _q('work_date',  {'type': 'string', 'format': 'date'}, 'Filter by work date (YYYY-MM-DD)'),
    ],
    resp={'200': {'description': 'Work logs scoped to the project',
                  'content': {'application/json': {'schema': {'type': 'object',
                      'properties': {
                          'ok': {'type': 'boolean'},
                          'project_id': {'type': 'integer'},
                          'work_logs': {'type': 'array', 'items': {'$ref': '#/components/schemas/WorkLog'}},
                      }}}}},
          **_err([400, 401, 403, 404])})
def list_worklogs():
    if not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
    project_id = request.args.get('project_id', type=int)
    resp, status = worklog_service.list_worklogs(
        project_id,
        request.args.get('user_id', type=int),
        request.args.get('work_date'),
        _actor())
    return jsonify(resp), status


@worklogs_bp.post('')
@api_doc('Create work log', ['Work Logs'],
    req={'type': 'object',
         'required': ['project_id', 'work_date', 'start_time', 'end_time'],
         'properties': {
             'project_id':        {'type': 'integer'},
             'work_date':         {'type': 'string', 'format': 'date', 'description': 'YYYY-MM-DD'},
             'start_time':        {'type': 'string', 'description': 'Start of work, e.g. 10:00 (24h) or 10:00 AM'},
             'end_time':          {'type': 'string', 'description': 'End of work, e.g. 12:30 (24h) or 12:30 PM. Must be after start_time.'},
             'worked_by_user_id': {'type': 'integer', 'description': 'Who performed the work (defaults to the authenticated user; '
                                    'selecting another member requires project lead/administrator permission)'},
             'issue_id':          {'type': 'integer', 'description': 'Optional issue in this project'},
             'description':       {'type': 'string'},
         }},
    resp={'201': _ok('#/components/schemas/WorkLog', 'Created'), **_err([400, 403, 404])})
def create_worklog():
    data = request.get_json(silent=True) or {}
    resp, status = worklog_service.create_worklog(data, _actor())
    return jsonify(resp), status


@worklogs_bp.patch('/<int:log_id>')
@api_doc('Update work log', ['Work Logs'],
    params=[_p('log_id', {'type': 'integer'}, 'Work log ID')],
req={'type': 'object',
          'description': 'Any subset of work log fields. When either start_time or end_time '
                         'is supplied, both are required and duration is recomputed on the backend.',
          'properties': {
              'work_date':        {'type': 'string', 'format': 'date'},
              'start_time':       {'type': 'string'},
              'end_time':         {'type': 'string'},
              'worked_by_user_id': {'type': 'integer'},
              'issue_id':         {'type': 'integer'},
              'description':      {'type': 'string'},
          }},
    resp={'200': _ok('#/components/schemas/WorkLog'), **_err([400, 401, 403, 404])})
def update_worklog(log_id):
    data = request.get_json(silent=True) or {}
    resp, status = worklog_service.update_worklog(log_id, data, _actor())
    return jsonify(resp), status


@worklogs_bp.delete('/<int:log_id>')
@api_doc('Delete work log', ['Work Logs'],
    params=[_p('log_id', {'type': 'integer'}, 'Work log ID')],
    resp={'200': _ok(), **_err([401, 403, 404])})
def delete_worklog(log_id):
    resp, status = worklog_service.delete_worklog(log_id, _actor())
    return jsonify(resp), status


@worklogs_bp.get('/timer/active')
@api_doc('Get the current active work timer', ['Work Logs'],
    params=[
        _q('project_id', {'type': 'integer'}, 'Optional project filter'),
    ],
    resp={'200': _ok('#/components/schemas/WorkTimerActive'), **_err([401])})
def timer_active():
    if not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
    resp, status = worklog_service.timer_active(_actor(), request.args.get('project_id', type=int))
    return jsonify(resp), status


@worklogs_bp.post('/timer/start')
@api_doc('Start work on an issue (automatic timer)', ['Work Logs'],
    req={'type': 'object',
         'required': ['project_id', 'issue_id'],
         'properties': {
             'project_id': {'type': 'integer', 'description': 'Project the issue belongs to'},
             'issue_id':   {'type': 'integer', 'description': 'Issue to work on'},
         }},
    resp={'201': _ok('#/components/schemas/WorkTimer', 'Timer started'), **_err([400, 401, 403, 404, 409])})
def timer_start():
    data = request.get_json(silent=True) or {}
    resp, status = worklog_service.timer_start(data, _actor())
    return jsonify(resp), status


@worklogs_bp.post('/timer/stop')
@api_doc('Stop the active work timer and create a Work Log', ['Work Logs'],
    req={'type': 'object',
         'description': 'Stops the authenticated user\'s active timer and finalizes a Work Log '
                        'with a server-computed duration.',
         'properties': {
             'issue_id': {'type': 'integer', 'description': 'Optional; mismatched active timer returns 409'},
         }},
    resp={'201': _ok(None, 'Work Log created'), **_err([400, 401, 409])})
def timer_stop():
    data = request.get_json(silent=True) or {}
    resp, status = worklog_service.timer_stop(data, _actor())
    return jsonify(resp), status