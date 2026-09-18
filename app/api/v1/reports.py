"""Reports API. Scope parsing/validation stays here; computation lives in
report_service."""
from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.models import Project, Sprint, User
from app.services import report_service
from app.utils.helpers import KANBAN_STATUSES, STATUS_LABELS, parse_any_date
from swagger_spec import _REPORT_Q, _err, _ok, _q, api_doc

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


def _report_scope():
    """Collect and parse the shared report filters from the query string."""
    project_id = request.args.get('project_id', type=int)
    sprint_id = request.args.get('sprint_id', type=int)
    assignee_id = request.args.get('assignee_id', type=int)

    status = (request.args.get('status') or '').strip().lower() or None
    if status and status not in KANBAN_STATUSES:
        status = None

    start_date = end_date = None
    start_raw = (request.args.get('start_date') or '').strip() or None
    end_raw = (request.args.get('end_date') or '').strip() or None
    start_dt = parse_any_date(start_raw) if start_raw else None
    end_dt = parse_any_date(end_raw) if end_raw else None
    if start_dt:
        start_date = start_dt.date()
    if end_dt:
        end_date = end_dt.date()

    return {
        'project_id': project_id,
        'sprint_id': sprint_id,
        'assignee_id': assignee_id,
        'status': status,
        'start_date': start_date,
        'end_date': end_date,
    }


def _report_validate(scope):
    """Validate referenced report filter IDs. Returns an error response tuple or None."""
    if scope['project_id'] and not Project.query.get(scope['project_id']):
        return jsonify({'ok': False, 'error': 'Project not found.'}), 404
    if scope['sprint_id']:
        sprint = Sprint.query.get(scope['sprint_id'])
        if not sprint:
            return jsonify({'ok': False, 'error': 'Sprint not found.'}), 404
        if scope['project_id'] and sprint.project_id != scope['project_id']:
            return jsonify({'ok': False, 'error': 'Sprint does not belong to the selected project.'}), 400
    if scope['assignee_id'] and not User.query.get(scope['assignee_id']):
        return jsonify({'ok': False, 'error': 'Assignee not found.'}), 404
    if scope['start_date'] and scope['end_date'] and scope['start_date'] > scope['end_date']:
        return jsonify({'ok': False, 'error': 'Start date must be on or before end date.'}), 400
    return None


def _run(handler):
    scope = _report_scope()
    bad = _report_validate(scope)
    if bad:
        return bad
    return jsonify(handler(scope))


@reports_bp.get('/filters')
@login_required
@api_doc('Get report filter options', ['Reports'],
    params=[_q('project_id', {'type': 'integer'})],
    resp={'200': _ok(), **_err([404])})
def filters():
    project_id = request.args.get('project_id', type=int)
    if project_id and not Project.query.get(project_id):
        return jsonify({'ok': False, 'error': 'Project not found.'}), 404
    return jsonify(report_service.filters({'project_id': project_id}))


@reports_bp.get('/summary')
@login_required
@api_doc('KPI summary', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def summary():
    return _run(report_service.summary)


@reports_bp.get('/project-health')
@login_required
@api_doc('Project health breakdown', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def project_health():
    return _run(report_service.project_health)


@reports_bp.get('/sprint-analytics')
@login_required
@api_doc('Sprint analytics', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def sprint_analytics():
    return _run(report_service.sprint_analytics)


@reports_bp.get('/velocity')
@login_required
@api_doc('Sprint velocity chart data', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def velocity():
    return _run(report_service.velocity)


@reports_bp.get('/status-distribution')
@login_required
@api_doc('Issues by status', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def status_distribution():
    return _run(report_service.status_distribution)


@reports_bp.get('/priority-distribution')
@login_required
@api_doc('Issues by priority', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def priority_distribution():
    return _run(report_service.priority_distribution)


@reports_bp.get('/overdue')
@login_required
@api_doc('Overdue issues', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def overdue():
    return _run(report_service.overdue)


@reports_bp.get('/completed-over-time')
@login_required
@api_doc('Completed issues over time', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def completed_over_time():
    return _run(report_service.completed_over_time)


@reports_bp.get('/team-performance')
@login_required
@api_doc('Team performance', ['Reports'],
    params=_REPORT_Q,
    resp={'200': _ok(), **_err([400, 404])})
def team_performance():
    return _run(report_service.team_performance)


@reports_bp.get('/drilldown')
@login_required
@api_doc('Drill-down detail list', ['Reports'],
    params=_REPORT_Q + [
        _q('type', {'type': 'string', 'enum': ['overdue', 'in_progress', 'status', 'velocity']},
           'Drill-down kind', True),
        _q('status', {'type': 'string'}, 'Status to drill-down on (when type=status)'),
        _q('sprint_id', {'type': 'integer'}, 'Sprint for velocity drill-down'),
    ],
    resp={'200': _ok(), **_err([400, 404])})
def drilldown():
    scope = _report_scope()
    bad = _report_validate(scope)
    if bad:
        return bad
    kind = (request.args.get('type') or '').strip().lower()
    status = (request.args.get('status') or '').strip().lower() or None
    sprint_id = request.args.get('sprint_id', type=int)
    resp, code = report_service.drilldown(scope, kind, status, sprint_id)
    return jsonify(resp), code