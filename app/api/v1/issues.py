from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.services import issue_service
from swagger_spec import _err, _ok, _p, _q, api_doc

issues_bp = Blueprint('issues', __name__, url_prefix='/issues')


def _actor():
    return current_user if current_user.is_authenticated else None


@issues_bp.get('')
@api_doc('List issues', ['Issues'],
    params=[
        _q('project',     {'type': 'string'},  'Project key, e.g. ECOM'),
        _q('project_id',  {'type': 'integer'}, 'Project ID'),
        _q('status',      {'type': 'string'},  'Issue status'),
        _q('priority',    {'type': 'string'},  'Issue priority'),
        _q('assignee',    {'type': 'string'},  'Assignee initials'),
        _q('assignee_id', {'type': 'integer'}, 'Assignee user ID'),
        _q('sprint',      {'type': 'integer'}, 'Sprint number'),
        _q('sprint_id',   {'type': 'integer'}, 'Sprint ID'),
        _q('top_level',   {'type': 'boolean'}, 'Only top-level tasks (exclude subtasks)'),
        _q('q',           {'type': 'string'},  'Search term (title, description, labels)'),
    ],
    resp={'200': {'description': 'Array of issues',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/Issue'}}}}}})
def list_issues():
    return jsonify(issue_service.list_issues(request.args))


@issues_bp.get('/<int:issue_id>')
@api_doc('Get issue', ['Issues'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    resp={'200': _ok('#/components/schemas/Issue'), **_err([404])})
def get_issue(issue_id):
    return jsonify(issue_service.get_issue(issue_id))


@issues_bp.post('')
@api_doc('Create issue', ['Issues'],
    req={
        'type': 'object',
        'required': ['summary', 'project'],
        'properties': {
            'summary':              {'type': 'string', 'description': 'Issue title (alias: title)', 'maxLength': 240},
            'project':              {'type': 'string', 'description': 'Project key', 'default': 'ECOM'},
            'issue_type':           {'type': 'string', 'enum': ['Story', 'Bug', 'Task', 'Epic'], 'default': 'Story'},
            'priority':             {'type': 'string', 'enum': ['Critical', 'Highest', 'High', 'Medium', 'Low', 'Lowest'], 'default': 'Medium'},
            'status':               {'type': 'string', 'enum': ['backlog', 'todo', 'in_progress', 'in_review', 'done'], 'default': 'backlog'},
            'start_date':           {'type': 'string'},
            'due_date':             {'type': 'string', 'description': 'Alias: end_date / target_date'},
            'assignees':            {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of user IDs'},
            'assignee':             {'type': 'string', 'description': 'Single assignee initials'},
            'points':               {'type': 'integer', 'minimum': 0},
            'sprint':               {'type': 'integer', 'description': 'Sprint number'},
            'labels':               {'type': 'array', 'items': {'type': 'string'}},
            'description':          {'type': 'string'},
            'acceptance_criteria':  {'type': 'string'},
            'parent_issue_id':      {'type': 'integer', 'description': 'Parent issue ID (omit/0 for a top-level Task; a Subtask is created when set). Parent must be a top-level task of the same project.'},
            'working_minutes':      {'type': 'integer', 'description': 'Task Working Hours in integer minutes (or "HH:MM"). Only accepted when status=done and must be positive; supplying it for a non-done task is rejected.'},
        },
    },
    resp={'201': _ok('#/components/schemas/Issue', 'Created'),
          **_err([400, 401, 403])})
def create_issue():
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.create_issue(data, _actor())
    return jsonify(resp), status


@issues_bp.patch('/<int:issue_id>')
@api_doc('Update issue', ['Issues'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    req={
        'type': 'object',
        'description': 'Any subset of issue fields',
        'properties': {
            'title':              {'type': 'string'},
            'summary':            {'type': 'string'},
            'issue_type':         {'type': 'string'},
            'priority':           {'type': 'string'},
            'status':             {'type': 'string'},
            'assignees':          {'type': 'array', 'items': {'type': 'integer'}},
            'assignee':           {'type': 'string'},
            'points':             {'type': 'integer'},
            'start_date':         {'type': 'string'},
            'due_date':           {'type': 'string'},
'labels':             {'type': 'array', 'items': {'type': 'string'}},
                'description':        {'type': 'string'},
                'acceptance_criteria':{'type': 'string'},
                'sprint':             {'type': 'integer'},
                'parent_issue_id':    {'type': 'integer', 'description': 'Move the task under a parent (0/null promotes it to a top-level Task). Parent must be a top-level task of the same project.'},
                'working_minutes':    {'type': 'integer', 'description': 'Task Working Hours in integer minutes (or "HH:MM"). Only accepted when the resulting status is done and must be positive. Reopening a done task (status left done) clears its working hours.'},
            },
    },
    resp={'200': _ok('#/components/schemas/Issue'), **_err([400, 401, 403, 404])})
def update_issue(issue_id):
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.update_issue(issue_id, data, _actor())
    return jsonify(resp), status


@issues_bp.post('/<int:issue_id>/move')
@api_doc('Move issue (Kanban drag-drop)', ['Issues'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    req={'type': 'object',
         'required': ['status'],
         'properties': {'status': {'type': 'string', 'enum': ['backlog', 'todo', 'in_progress', 'in_review', 'done']}}},
    resp={'200': _ok('#/components/schemas/Issue'), **_err([400, 401, 403, 404])})
def move_issue(issue_id):
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.move_issue(issue_id, data, _actor())
    return jsonify(resp), status


@issues_bp.post('/<int:issue_id>/reorder')
@api_doc('Reorder a subtask (Move Up / Move Down)', ['Issues'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    req={'type': 'object',
         'description': 'Pass direction ("up" | "down") to swap with the adjacent sibling, '
                        'or an absolute 1-based subtask_order. A top-level task cannot be reordered this way.',
         'properties': {'direction': {'type': 'string', 'enum': ['up', 'down']},
                        'subtask_order': {'type': 'integer'}}},
    resp={'200': _ok('#/components/schemas/Issue'), **_err([400, 401, 403, 404])})
def reorder_issue(issue_id):
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.reorder_subtask(issue_id, data, _actor())
    return jsonify(resp), status


@issues_bp.delete('/<int:issue_id>')
@api_doc('Delete issue', ['Issues'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    req={'type': 'object',
         'description': 'Optional body. Deleting a parent whose subtasks exist requires confirm_subtasks=true; otherwise it responds 400 with needs_confirmation.',
         'properties': {'confirm_subtasks': {'type': 'boolean', 'description': 'Delete a parent task and all of its subtasks.'}}},
    resp={'200': {'description': 'Deleted',
                  'content': {'application/json': {'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}}}},
          **_err([400, 401, 403, 404])})
def delete_issue(issue_id):
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.delete_issue(issue_id, _actor(), data)
    return jsonify(resp), status


@issues_bp.get('/<int:issue_id>/comments')
@api_doc('List issue comments', ['Comments'],
    params=[_p('issue_id', {'type': 'integer'}, 'Issue ID')],
    resp={'200': {'description': 'Array of comments',
                  'content': {'application/json': {'schema': {'type': 'array', 'items': {'$ref': '#/components/schemas/Comment'}}}}},
          **_err([404])})
def issue_comments(issue_id):
    return jsonify(issue_service.issue_comments(issue_id))