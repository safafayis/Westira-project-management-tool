from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Issue, Project
from app.utils.helpers import (
    active_project_sprint,
    issue_dict,
    open_issue_count,
    project_dict,
    project_member_count,
    recent_activity,
    sprint_api_dict,
    sprint_progress_pct,
    sprint_stats_dict,
    tasks_due_this_week,
    user_dict,
)
from swagger_spec import _err, _ok, api_doc

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.get('')
@login_required
@api_doc('Dashboard summary', ['Dashboard'],
    resp={'200': _ok('#/components/schemas/Dashboard'), **_err([401])})
def dashboard():
    me = current_user
    projects_all = Project.query.all()
    selected_key = (request.args.get('project') or '').strip().upper()
    selected_project = next(
        (p for p in projects_all if p.key == selected_key), None
    ) if selected_key else None
    if selected_project is None:
        selected_project = projects_all[0] if projects_all else None

    issues = Issue.query.filter_by(project_id=selected_project.id).all() if selected_project else []
    active_sprint = active_project_sprint(selected_project)
    sprint_stats = sprint_stats_dict(active_sprint, issues) if active_sprint else None

    open_issues = open_issue_count(issues)
    tasks_due = tasks_due_this_week(issues)
    sprint_pct = sprint_progress_pct(sprint_stats)
    my_tasks = [i for i in issues if i.assignee_initials == me.initials][:6]

    return jsonify({
        'user': user_dict(me),
        'kpis': [
            {'value': open_issues, 'label': 'Open Issues'},
            {'value': tasks_due, 'label': 'Tasks Due This Week'},
            {'value': f'{sprint_pct}%', 'label': 'Sprint Progress'},
            {'value': project_member_count(selected_project), 'label': 'Team Members'},
        ],
        'projects': [project_dict(p) for p in projects_all],
        'active_sprint': sprint_api_dict(active_sprint, issues) if active_sprint else None,
        'my_tasks': [issue_dict(i) for i in my_tasks],
        'recent_activities': recent_activity(selected_project, limit=8),
    })