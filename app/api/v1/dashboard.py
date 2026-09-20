from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Issue, Project
from app.utils.helpers import (
    active_project_sprint,
    issue_dict,
    open_issue_count,
    project_dict,
    project_member_count,
    project_progress_batch,
    recent_activity,
    resolve_selected_project,
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
    selected_project = resolve_selected_project(request.args.get('project') or '')

    issues = Issue.query.filter_by(project_id=selected_project.id).all() if selected_project else []
    active_sprint = active_project_sprint(selected_project)
    sprint_stats = sprint_stats_dict(active_sprint, issues) if active_sprint else None

    open_issues = open_issue_count(issues)
    tasks_due = tasks_due_this_week(issues)
    sprint_pct = sprint_progress_pct(sprint_stats)
    my_tasks = [i for i in issues if i.assignee_initials == me.initials][:6]
    _pbatch = project_progress_batch()
    _empty = {'total_issues': 0, 'completed_issues': 0}

    return jsonify({
        'user': user_dict(me),
        'kpis': [
            {'value': open_issues, 'label': 'Open Issues'},
            {'value': tasks_due, 'label': 'Tasks Due This Week'},
            {'value': f'{sprint_pct}%', 'label': 'Sprint Progress'},
            {'value': project_member_count(selected_project), 'label': 'Team Members'},
        ],
        'projects': [project_dict(p, _pbatch.get(p.id) or _empty) for p in projects_all],
        'active_sprint': sprint_api_dict(active_sprint, issues) if active_sprint else None,
        'my_tasks': [issue_dict(i) for i in my_tasks],
        'recent_activities': recent_activity(selected_project, limit=8),
    })