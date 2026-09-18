from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.models import Activity, Issue, Project, Sprint, User
from app.utils.helpers import issue_dict, project_dict, sprint_api_dict, user_dict
from swagger_spec import _err, _ok, api_doc

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.get('')
@login_required
@api_doc('Dashboard summary', ['Dashboard'],
    resp={'200': _ok('#/components/schemas/Dashboard'), **_err([401])})
def dashboard():
    me = current_user
    projects_all = Project.query.all()
    issues_all = Issue.query.all()
    active_sprint = Sprint.query.filter_by(status='Active').first()
    users_all = User.query.all()

    open_issues = sum(1 for i in issues_all if i.status != 'done')
    tasks_due = sum(1 for i in issues_all if i.due_date and i.status != 'done')
    sprint_pct = round((active_sprint.story_points_done or 0) / (active_sprint.story_points_total or 1) * 100) if active_sprint else 0
    my_tasks = [i for i in issues_all if i.assignee_initials == me.initials][:6]

    return jsonify({
        'user': user_dict(me),
        'kpis': [
            {'value': open_issues, 'label': 'Open Issues'},
            {'value': tasks_due, 'label': 'Tasks Due This Week'},
            {'value': f'{sprint_pct}%', 'label': 'Sprint Progress'},
            {'value': len(users_all), 'label': 'Team Members'},
        ],
        'projects': [project_dict(p) for p in projects_all],
        'active_sprint': sprint_api_dict(active_sprint, issues_all) if active_sprint else None,
        'my_tasks': [issue_dict(i) for i in my_tasks],
        'recent_activities': [{'id': a.id, 'icon': a.icon, 'color': a.color,
                               'text': a.text, 'detail': a.detail, 'time': a.time}
                              for a in Activity.query.order_by(Activity.id.desc()).limit(8).all()],
    })