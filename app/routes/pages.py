"""HTML page routes. Endpoints keep their monolith names ('login', 'dashboard',
'dashboard', 'pro-required' pages...) so url_for() in templates keeps working.

Login/register keep their GET+POST hybrid behavior for the form fallback; the
JSON SPA frontends now post to /api/v1/auth/* instead.
"""
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import Activity, Comment, Issue, Notification, Project, ProjectMembers, Sprint, User
from app.services import auth_service
from app.services.report_service import _project_health
from app.utils.helpers import (
    active_project_sprint,
    context_issues,
    context_project,
    context_sprint_stats,
    context_sprints,
    issue_dict,
    open_issue_count,
    parse_any_date,
    project_member_count,
    recent_activity,
    sprint_progress_pct,
    sprint_stats_dict,
    tasks_due_this_week,
    user_dict,
)


def register_pages(app):

    @app.route('/')
    def index():
        return redirect(url_for('dashboard'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            if request.is_json:
                return jsonify({'ok': True, 'redirect': url_for('dashboard')})
            return redirect(url_for('dashboard'))
        is_json = request.is_json
        data = request.get_json(silent=True) if is_json else None
        if request.method == 'POST':
            email = ((data or {}).get('email') if is_json
                     else request.form.get('email') or '').strip().lower()
            password = (data or {}).get('password') if is_json else request.form.get('password') or ''
            user = auth_service.authenticate(email, password)
            if user:
                if user.status and user.status.lower() != 'active':
                    if is_json:
                        return jsonify({'ok': False, 'error': 'This account has been deactivated. Contact your workspace administrator.'}), 403
                    flash('This account has been deactivated. Contact your workspace administrator.', 'error')
                    return render_template('auth/login.html', active_page='login')
                login_user(user)
                if is_json:
                    return jsonify({'ok': True, 'user': user_dict(user), 'redirect': url_for('dashboard')})
                return redirect(url_for('dashboard'))
            if is_json:
                return jsonify({'ok': False, 'error': 'Invalid email or password.'}), 401
            flash('Invalid email or password.', 'error')
        return render_template('auth/login.html', active_page='login')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            if request.is_json:
                return jsonify({'ok': True, 'redirect': url_for('dashboard')})
            return redirect(url_for('dashboard'))
        is_json = request.is_json
        data = request.get_json(silent=True) if is_json else None

        if request.method == 'POST':
            user, error = auth_service.register(data if is_json else {
                'name': request.form.get('name') or '',
                'email': request.form.get('email') or '',
                'password': request.form.get('password') or '',
                'role': request.form.get('role') or '',
                'team': request.form.get('team'),
            })
            if error:
                if is_json:
                    return jsonify({'ok': False, 'error': error}), 400
                flash(error, 'error')
                return render_template('auth/register.html', active_page='register')
            login_user(user)
            if is_json:
                return jsonify({'ok': True, 'user': user_dict(user), 'redirect': url_for('dashboard')}), 201
            flash('Account created. Welcome to ABC!', 'success')
            return redirect(url_for('dashboard'))
        return render_template('auth/register.html', active_page='register')

    @app.route('/logout', methods=['GET', 'POST'])
    @login_required
    def logout():
        logout_user()
        if request.is_json:
            return jsonify({'ok': True})
        return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        me = current_user
        projects_all = Project.query.all()
        selected_key = (request.args.get('project') or '').strip().upper()
        selected_project = next(
            (p for p in projects_all if p.key == selected_key), None
        ) if selected_key else None
        if selected_project is None:
            selected_project = projects_all[0] if projects_all else None

        project_issues = context_issues(selected_project) if selected_project else []
        active_sprint = active_project_sprint(selected_project)
        sprint_stats = sprint_stats_dict(active_sprint, project_issues) if active_sprint else None

        open_issues = open_issue_count(project_issues)
        tasks_due = tasks_due_this_week(project_issues)
        sprint_pct = sprint_progress_pct(sprint_stats)
        member_count = project_member_count(selected_project)
        my_tasks = [i for i in project_issues if i.assignee_initials == me.initials][:6]

        kpis = [
            {'value': open_issues, 'label': 'Open Issues', 'trend': '', 'up': True,
             'icon': 'alert-circle', 'color': '#0891b2', 'bg': '#ecfeff'},
            {'value': tasks_due, 'label': 'Tasks Due This Week', 'trend': '', 'up': True,
             'icon': 'calendar-clock', 'color': '#d97706', 'bg': '#fffbeb'},
            {'value': f'{sprint_pct}%', 'label': 'Sprint Progress', 'trend': '', 'up': True,
             'icon': 'timer', 'color': '#7c3aed', 'bg': '#f5f3ff'},
            {'value': member_count, 'label': 'Team Members', 'trend': '', 'up': True,
             'icon': 'users', 'color': '#059669', 'bg': '#ecfdf5'},
        ]

        context = {
            'active_page': 'dashboard', 'kpis': kpis,
            'projects': projects_all, 'issues': project_issues,
            'active_sprint': sprint_stats, 'my_tasks': my_tasks,
            'notifications': Notification.query.order_by(Notification.id.desc()).limit(4).all(),
            'activity': recent_activity(selected_project, limit=8),
            'user_projects': projects_all, 'selected_project': selected_project,
        }

        if me.plan == 'pro':
            return render_template('dashboard/dashboard_pro.html', **context)
        return render_template('dashboard/dashboard_standard.html', **context)

    @app.route('/people-hub')
    @login_required
    def people_hub():
        if current_user.plan != 'pro':
            flash("You don't have permission to access People Hub.", 'error')
            return redirect(url_for('dashboard'))
        return render_template('team/people_hub.html', active_page='people_hub')

    @app.route('/projects')
    @login_required
    def projects():
        member_rows = db.session.query(ProjectMembers, User).join(User, User.id == ProjectMembers.user_id).all()
        members_per_project = {}
        for pm, u in member_rows:
            members_per_project.setdefault(pm.project_id, []).append(u)
        return render_template('projects/projects.html', active_page='projects',
                               projects=Project.query.all(),
                               members_per_project=members_per_project,
                               users=User.query.all())

    @app.route('/project/<key>')
    @app.route('/project')
    @login_required
    def project_overview(key='ECOM'):
        project = context_project(key)
        members = db.session.query(User).join(ProjectMembers, ProjectMembers.user_id == User.id) \
            .filter(ProjectMembers.project_id == project.id).all()
        issues = context_issues(project)
        sprints = context_sprints(project)

        today = datetime.utcnow().date()

        # Project progress uses the app's established issue-completion
        # definition (done issues / total issues), matching the Reports page.
        total = len(issues)
        completed = sum(1 for i in issues if i.status == 'done')
        project_progress = round(completed / total * 100) if total else 0

        # Active sprint uses the established rule (status == 'Active'); its
        # stats are computed from the sprint's real issues (same values as the
        # Dashboard and /api/v1/dashboard for the same project).
        active_sprint = active_project_sprint(project)
        active_sprint_stats = sprint_stats_dict(active_sprint, issues) if active_sprint else None
        sprint_pct = sprint_progress_pct(active_sprint_stats)

        # Upcoming deadlines = non-done issues with a due date >= today,
        # nearest due date first. Overdue issues are counted separately, as the
        # existing reports/overdue logic already distinguishes them.
        overdue_issues = 0
        deadlines = []
        for issue in issues:
            if issue.status == 'done':
                continue
            due = parse_any_date(issue.due_date)
            if due is None:
                continue
            if due.date() < today:
                overdue_issues += 1
            else:
                deadlines.append(issue)
        deadlines.sort(key=lambda i: parse_any_date(i.due_date))

        # Project Health: the overall rating reuses the established reports
        # rules; metric cards use real data where it exists and fall back to
        # the existing 'Not available' state otherwise (no invented values).
        due = parse_any_date(project.due_date)
        if due is None:
            health_schedule = 'Not available'
        else:
            health_schedule = 'At Risk' if (due.date() - today).days <= 30 else 'On Track'
        health_budget = 'Not available'
        health_scope = 'Not available'
        member_count = len(members)
        open_work = total - completed
        if member_count == 0:
            health_capacity = 'Not available'
        else:
            load = open_work / member_count
            health_capacity = 'Good' if load <= 3 else ('At Risk' if load <= 6 else 'Critical')
        health_overall = _project_health(project, total, completed, overdue_issues, sprint_pct or None)

        return render_template('projects/project_overview.html', active_page='project',
                               project=project, sprints=sprints, issues=issues,
                               members=members, active_sprint_stats=active_sprint_stats,
                               sprint_pct=sprint_pct, project_progress=project_progress,
                               deadlines=deadlines, health_overall=health_overall,
                               health_schedule=health_schedule, health_budget=health_budget,
                               health_scope=health_scope, health_capacity=health_capacity)

    @app.route('/kanban/<key>')
    @app.route('/kanban')
    @login_required
    def kanban(key='ECOM'):
        project = context_project(key)
        members = db.session.query(User).join(ProjectMembers, ProjectMembers.user_id == User.id) \
            .filter(ProjectMembers.project_id == project.id).all()
        return render_template('work/kanban.html', active_page='kanban',
                               project=project, sprints=context_sprints(project),
                               issues=context_issues(project), members=members)

    @app.route('/backlog/<key>')
    @app.route('/backlog')
    @login_required
    def backlog(key='ECOM'):
        project = context_project(key)
        return render_template('work/backlog.html', active_page='backlog',
                               project=project, sprints=context_sprints(project),
                               issues=context_issues(project))

    @app.route('/sprints/<key>')
    @app.route('/sprints')
    @login_required
    def sprints(key='ECOM'):
        project = context_project(key)
        return render_template('sprints/sprints.html', active_page='sprints',
                               project=project, sprints=context_sprint_stats(project),
                               issues=context_issues(project),
                               project_tasks=[issue_dict(i) for i in context_issues(project)])

    @app.route('/issue/<int:issue_id>')
    @login_required
    def issue_detail(issue_id):
        issue = Issue.query.get(issue_id) or Issue.query.first()
        comments = Comment.query.filter_by(issue_id=issue.id).order_by(Comment.id).all()
        project = issue.project
        return render_template('issues/issue_detail.html', active_page='issue',
                               issue=issue, project=project, comments=comments,
                               users=User.query.all(), sprints=context_sprints(project))

    @app.route('/issue')
    @login_required
    def issue_default():
        return issue_detail(Issue.query.first().id)

    @app.route('/my-work')
    @login_required
    def my_work():
        me = current_user
        all_issues = Issue.query.all()
        my_tasks = [i for i in all_issues if i.assignee_initials == me.initials][:8]
        completed_tasks = [i for i in all_issues if i.status == 'done' and i.assignee_initials == me.initials]
        return render_template('work/my_work.html', active_page='my_work',
                               users=User.query.all(), all_issues=all_issues,
                               me=me, my_tasks=my_tasks,
                               completed_tasks=completed_tasks)

    @app.route('/ai-assistant')
    @login_required
    def ai_assistant():
        return render_template('ai/ai_assistant.html', active_page='ai-assistant')

    @app.route('/team')
    @login_required
    def team():
        return render_template('team/team.html', active_page='team', users=User.query.all())

    @app.route('/reports')
    @login_required
    def reports():
        return render_template('reports/reports.html', active_page='reports',
                               projects=Project.query.all(), sprints=Sprint.query.all(),
                               issues=Issue.query.all(), users=User.query.all())

    @app.route('/calendar')
    @login_required
    def calendar():
        return render_template('work/calendar.html', active_page='calendar',
                               projects=Project.query.all(), sprints=Sprint.query.all(),
                               issues=Issue.query.all(), users=User.query.all())

    @app.route('/notifications')
    @login_required
    def notifications():
        return render_template('notifications/notifications.html', active_page='notifications',
                               notifications=Notification.query.order_by(
                                   Notification.id.desc()).all())