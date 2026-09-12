import os
import random
from datetime import datetime, timedelta

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user as login_current_user, login_required, login_user, logout_user
from sqlalchemy import inspect as sa_inspect, text as sa_text

from config import Config
from models import (
    Activity,
    Comment,
    Issue,
    IssueAssignees,
    Notification,
    Project,
    ProjectMembers,
    Sprint,
    User,
    db,
)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to continue.'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def update_last_seen():
    if login_current_user.is_authenticated:
        now = datetime.utcnow()
        if not login_current_user.last_seen or (now - login_current_user.last_seen).total_seconds() > 60:
            login_current_user.last_seen = now
            db.session.commit()

# ============================================================
# SERIALIZERS
# ============================================================

def user_dict(u):
    now = datetime.utcnow()
    is_online = u.last_seen is not None and (now - u.last_seen) < timedelta(minutes=5)
    return {'id': u.id, 'name': u.name, 'initials': u.initials, 'role': u.role,
            'team': u.team, 'email': u.email, 'color': u.color, 'plan': u.plan,
            'capacity': u.capacity, 'active_projects': u.active_projects,
            'current_tasks': u.current_tasks, 'status': u.status,
            'is_online': is_online, 'last_seen': u.last_seen.isoformat() if u.last_seen else None,
            'created_at': u.created_at.isoformat() if u.created_at else None}


def project_dict(p):
    return {
        'id': p.id, 'key': p.key, 'name': p.name, 'lead_id': p.lead_id,
        'lead_initials': p.lead_initials, 'color': p.color, 'status': p.status,
        'start_date': p.start_date, 'due_date': p.due_date, 'progress': p.progress,
        'description': p.description,
        'health': {'schedule': p.health_schedule, 'budget': p.health_budget,
                   'scope': p.health_scope, 'capacity': p.health_capacity},
    }


def issue_dict(i):
    assignee_records = IssueAssignees.query.filter_by(issue_id=i.id).all()
    assignee_users = [User.query.get(r.user_id) for r in assignee_records if User.query.get(r.user_id)]
    all_initials = []
    if i.assignee_initials and i.assignee_initials not in [u.initials for u in assignee_users]:
        all_initials.append(i.assignee_initials)
    all_initials += [u.initials for u in assignee_users]
    return {
        'id': i.id, 'project': i.project.key if i.project else 'ECOM',
        'number': i.number, 'key': f'{i.project.key}-{i.number}' if i.project else f'ECOM-{i.number}',
        'title': i.title, 'type': i.issue_type, 'type_color': i.type_color,
        'priority': i.priority, 'priority_color': i.priority_color, 'points': i.points,
        'assignee_id': i.assignee_id, 'assignee': i.assignee_initials,
        'assignee_color': i.assignee_color, 'assignee_initials_list': all_initials,
        'due': i.due_date, 'start': i.start_date,
        'labels': i.labels or [],
        'status': i.status, 'sprint': i.sprint.number if i.sprint else None,
        'description': i.description, 'acceptance_criteria': i.acceptance_criteria,
        'reporter': i.reporter_id, 'created': i.created_at,
    }


def context_project(key='ECOM'):
    return Project.query.filter_by(key=key).first() or Project.query.first()


def context_sprints(project):
    return Sprint.query.filter_by(project_id=project.id).order_by(Sprint.number).all()


def sprint_stats_dict(sprint, issues):
    """Build a sprint display dict with task/point stats computed from the
    project's actual issues that belong to this sprint."""
    sp_issues = [i for i in issues if i.sprint_id == sprint.id]
    story_points_total = sum(i.points or 0 for i in sp_issues)
    story_points_done = sum((i.points or 0) for i in sp_issues if i.status == 'done')
    backlog = sum(1 for i in sp_issues if i.status == 'backlog')
    to_do = sum(1 for i in sp_issues if i.status == 'todo')
    in_progress = sum(1 for i in sp_issues if i.status == 'in_progress')
    in_review = sum(1 for i in sp_issues if i.status == 'in_review')
    done = sum(1 for i in sp_issues if i.status == 'done')
    total = backlog + to_do + in_progress + in_review + done
    return {
        'id': sprint.id,
        'number': sprint.number,
        'name': sprint.name,
        'project_id': sprint.project_id,
        'start_date': format_date(sprint.start_date),
        'end_date': format_date(sprint.end_date),
        'goal': sprint.goal,
        'description': sprint.description or '',
        'status': sprint.status,
        'to_do': to_do,
        'in_progress': in_progress,
        'in_review': in_review,
        'done': done,
        'backlog': backlog,
        'total': total,
        'remaining': total - done,
        'progress': round(done / total * 100) if total else 0,
        'story_points_total': story_points_total,
        'story_points_done': story_points_done,
    }


def context_sprint_stats(project):
    return [sprint_stats_dict(sp, context_issues(project)) for sp in context_sprints(project)]


def context_issues(project):
    return Issue.query.filter_by(project_id=project.id).order_by(Issue.position).all()


def parse_date(value):
    if not value:
        return None
    for fmt in ('%b %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def format_date(value):
    d = parse_date(value)
    return d.strftime('%b %d, %Y') if d else (value or '')


PRIORITY_COLORS = {
    'Highest': '#dc2626', 'High': '#d97706', 'Medium': '#0891b2', 'Low': '#4f46e5', 'Lowest': '#6b7280',
    'Critical': '#dc2626',
}
ISSUE_TYPE_COLORS = {'Story': '#059669', 'Bug': '#dc2626', 'Task': '#4f46e5', 'Epic': '#7c3aed'}
KANBAN_STATUSES = ['backlog', 'todo', 'in_progress', 'in_review', 'done']


def validate_task_dates(project, start_date, end_date):
    """Validate a task's dates fall within the project date range.

    Returns (ok, error_message).
    """
    p_start = parse_date(project.start_date)
    p_end = parse_date(project.due_date)
    t_start = parse_date(start_date)
    t_end = parse_date(end_date)

    if t_start and t_end and t_end < t_start:
        return False, "Task target date cannot be earlier than the task start date."
    if p_start and t_start and t_start < p_start:
        return False, "Task start date cannot be earlier than the project start date."
    if p_end and t_start and t_start > p_end:
        return False, "Task start date cannot be later than the project target date."
    if p_start and t_end and t_end < p_start:
        return False, "Target Date cannot be earlier than the project start date."
    if p_end and t_end and t_end > p_end:
        return False, "Target Date cannot be later than the project target date."
    return True, None


def validate_project_dates(start_date, end_date):
    """Project target date must not be earlier than project start date."""
    s = parse_date(start_date)
    e = parse_date(end_date)
    if s and e and e < s:
        return False, "Project target date cannot be earlier than the project start date."
    return True, None


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if login_current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html', active_page='login')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if login_current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        role = (request.form.get('role') or '').strip()
        team = (request.form.get('team') or '').strip() or 'General'

        if not name or not email or not password or not role:
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html', active_page='register')

        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
            return render_template('register.html', active_page='register')

        initials = ''.join(p[0] for p in name.split() if p)[:2].upper()
        if not initials:
            initials = 'XX'

        u = User(
            name=name,
            initials=initials,
            email=email,
            plan='lite',
            role=role,
            team=team,
            capacity=50,
            active_projects=0,
            current_tasks=0,
            color='#4f46e5',
            status='Active',
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        flash('Account created. Welcome to ABC!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html', active_page='register')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    me = login_current_user
    projects_all = Project.query.all()
    issues_all = Issue.query.all()
    active_sprint = Sprint.query.filter_by(status='Active').first()
    users_all = User.query.all()

    open_issues = sum(1 for i in issues_all if i.status != 'done')
    tasks_due = sum(1 for i in issues_all if i.due_date and i.status != 'done')
    sprint_pct = round((active_sprint.story_points_done or 0) / (active_sprint.story_points_total or 1) * 100) if active_sprint else 0
    my_tasks = [i for i in issues_all if i.assignee_initials == me.initials][:6]

    kpis = [
        {'value': open_issues, 'label': 'Open Issues', 'trend': '-4', 'up': False,
         'icon': 'alert-circle', 'color': '#0891b2', 'bg': '#ecfeff'},
        {'value': tasks_due, 'label': 'Tasks Due This Week', 'trend': '2 soon', 'up': True,
         'icon': 'calendar-clock', 'color': '#d97706', 'bg': '#fffbeb'},
        {'value': f'{sprint_pct}%', 'label': 'Sprint Progress', 'trend': '+12%', 'up': True,
         'icon': 'timer', 'color': '#7c3aed', 'bg': '#f5f3ff'},
        {'value': len(users_all), 'label': 'Team Members', 'trend': '+1', 'up': True,
         'icon': 'users', 'color': '#059669', 'bg': '#ecfdf5'},
    ]

    selected_project = projects_all[0] if projects_all else None

    context = {
        'active_page': 'dashboard', 'kpis': kpis,
        'projects': projects_all, 'issues': issues_all,
        'active_sprint': active_sprint, 'my_tasks': my_tasks,
        'notifications': Notification.query.order_by(Notification.id.desc()).limit(4).all(),
        'activity': Activity.query.order_by(Activity.id.desc()).limit(8).all(),
        'user_projects': projects_all, 'selected_project': selected_project,
    }

    if me.plan == 'pro':
        return render_template('dashboard_pro.html', **context)
    return render_template('dashboard_standard.html', **context)


@app.route('/people-hub')
@login_required
def people_hub():
    if login_current_user.plan != 'pro':
        flash("You don't have permission to access People Hub.", 'error')
        return redirect(url_for('dashboard'))
    return render_template('people_hub.html', active_page='people_hub')


@app.route('/projects')
@login_required
def projects():
    member_rows = db.session.query(ProjectMembers, User).join(User, User.id == ProjectMembers.user_id).all()
    members_per_project = {}
    for pm, u in member_rows:
        members_per_project.setdefault(pm.project_id, []).append(u)
    return render_template('projects.html', active_page='projects',
                           projects=Project.query.all(),
                           members_per_project=members_per_project,
                           users=User.query.all())


@app.route('/project/<key>')
@app.route('/project')
@login_required
def project_overview(key='ECOM'):
    project = context_project(key)
    from models import ProjectMembers
    members = db.session.query(User).join(ProjectMembers, ProjectMembers.user_id == User.id) \
        .filter(ProjectMembers.project_id == project.id).all()
    return render_template('project_overview.html', active_page='project',
                           project=project, sprints=context_sprints(project),
                           issues=context_issues(project), members=members)


@app.route('/kanban/<key>')
@app.route('/kanban')
@login_required
def kanban(key='ECOM'):
    project = context_project(key)
    from models import ProjectMembers
    members = db.session.query(User).join(ProjectMembers, ProjectMembers.user_id == User.id) \
        .filter(ProjectMembers.project_id == project.id).all()
    return render_template('kanban.html', active_page='kanban',
                           project=project, sprints=context_sprints(project),
                           issues=context_issues(project), members=members)


@app.route('/backlog/<key>')
@app.route('/backlog')
@login_required
def backlog(key='ECOM'):
    project = context_project(key)
    return render_template('backlog.html', active_page='backlog',
                           project=project, sprints=context_sprints(project),
                           issues=context_issues(project))


@app.route('/sprints/<key>')
@app.route('/sprints')
@login_required
def sprints(key='ECOM'):
    project = context_project(key)
    return render_template('sprints.html', active_page='sprints',
                           project=project, sprints=context_sprint_stats(project),
                           issues=context_issues(project),
                           project_tasks=[issue_dict(i) for i in context_issues(project)])


@app.route('/issue/<int:issue_id>')
@login_required
def issue_detail(issue_id):
    issue = Issue.query.get(issue_id) or Issue.query.first()
    comments = Comment.query.filter_by(issue_id=issue.id).order_by(Comment.id).all()
    project = issue.project
    return render_template('issue_detail.html', active_page='issue',
                           issue=issue, project=project, comments=comments,
                           users=User.query.all(), sprints=context_sprints(project))


@app.route('/issue')
@login_required
def issue_default():
    return issue_detail(Issue.query.first().id)


@app.route('/my-work')
@login_required
def my_work():
    me = login_current_user
    all_issues = Issue.query.all()
    my_tasks = [i for i in all_issues if i.assignee_initials == me.initials][:8]
    completed_tasks = [i for i in all_issues if i.status == 'done' and i.assignee_initials == me.initials]
    return render_template('my_work.html', active_page='my_work',
                           users=User.query.all(), all_issues=all_issues,
                           me=me, my_tasks=my_tasks,
                           completed_tasks=completed_tasks)


@app.route('/ai-assistant')
@login_required
def ai_assistant():
    return render_template('ai_assistant.html', active_page='ai-assistant')


@app.route('/team')
@login_required
def team():
    return render_template('team.html', active_page='team', users=User.query.all())


@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html', active_page='reports',
                           projects=Project.query.all(), sprints=Sprint.query.all(),
                           issues=Issue.query.all(), users=User.query.all())


@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html', active_page='calendar',
                           projects=Project.query.all(), sprints=Sprint.query.all(),
                           issues=Issue.query.all(), users=User.query.all())


@app.route('/notifications')
@login_required
def notifications():
    return render_template('notifications.html', active_page='notifications',
                           notifications=Notification.query.order_by(
                               Notification.id.desc()).all())


@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html', active_page='settings',
                           users=User.query.order_by(User.name).all())


# ============================================================
# REST API
# ============================================================

@app.route('/api/issues')
def api_issues():
    q = Issue.query
    project = request.args.get('project')
    status = request.args.get('status')
    assignee = request.args.get('assignee')
    sprint = request.args.get('sprint')
    search = request.args.get('q')
    if project:
        q = q.join(Project).filter(Project.key == project.upper())
    if status:
        q = q.filter(Issue.status == status)
    if assignee:
        users = [u for u in User.query.all() if u.initials == assignee.upper()]
        if not users:
            q = q.filter(False)
        else:
            user_ids = [u.id for u in users]
            q = q.outerjoin(IssueAssignees, IssueAssignees.issue_id == Issue.id).filter(
                db.or_(Issue.assignee_id.in_(user_ids), IssueAssignees.user_id.in_(user_ids))
            ).distinct()
    if sprint:
        try:
            sprint_num = int(sprint)
        except (TypeError, ValueError):
            return jsonify([])
        sp = Sprint.query.filter_by(number=sprint_num).first()
        if not sp:
            return jsonify([])
        q = q.filter(Issue.sprint_id == sp.id)
    if search:
        term = f'%{search.strip().lower()}%'
        q = q.filter(db.or_(
            db.func.lower(Issue.title).like(term),
            db.cast(Issue.number, db.String).like(term),
            db.func.lower(db.func.coalesce(Issue.description, '')).like(term),
            db.func.lower(db.func.coalesce(db.cast(Issue.labels, db.Text), '')).like(term),
        ))
    return jsonify([issue_dict(i) for i in q.order_by(Issue.position).all()])


@app.route('/api/issues/<int:issue_id>')
def api_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    return jsonify(issue_dict(issue))


@app.route('/api/issues', methods=['POST'])
def api_create_issue():
    data = request.get_json(silent=True) or {}

    summary = (data.get('summary') or data.get('title') or '').strip()
    if not summary:
        return jsonify({'ok': False, 'error': 'Summary is required.'}), 400
    if len(summary) > 240:
        return jsonify({'ok': False, 'error': 'Summary must be 240 characters or fewer.'}), 400

    project = Project.query.filter_by(key=(data.get('project') or 'ECOM').upper()).first()
    if not project:
        return jsonify({'ok': False, 'error': 'Invalid project.'}), 400

    issue_type = data.get('issue_type') or 'Story'
    if issue_type not in ISSUE_TYPE_COLORS:
        return jsonify({'ok': False, 'error': 'Invalid issue type.'}), 400

    priority = data.get('priority') or 'Medium'
    if priority not in PRIORITY_COLORS:
        return jsonify({'ok': False, 'error': 'Invalid priority.'}), 400

    status = str(data.get('status') or 'backlog').strip().lower()
    if status not in KANBAN_STATUSES:
        return jsonify({'ok': False, 'error': 'Invalid status.'}), 400

    start_date = data.get('start_date')
    end_date = data.get('due_date') or data.get('end_date') or data.get('target_date')
    ok, err = validate_task_dates(project, start_date, end_date)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    assignees_data = data.get('assignees')
    single_assignee = data.get('assignee')

    primary_user = None
    all_assignee_users = []

    if assignees_data and isinstance(assignees_data, list) and len(assignees_data) > 0:
        seen_ids = set()
        for uid in assignees_data:
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            if uid_int in seen_ids:
                continue
            seen_ids.add(uid_int)
            user = User.query.get(uid_int)
            if not user:
                return jsonify({'ok': False, 'error': f'Assignee user ID {uid_int} does not exist.'}), 400
            if user.status and user.status.lower() != 'active':
                return jsonify({'ok': False, 'error': f'Assignee {user.name} must be an active user.'}), 400
            all_assignee_users.append(user)
        if all_assignee_users:
            primary_user = all_assignee_users[0]
    elif single_assignee:
        assignee = User.query.filter_by(initials=str(single_assignee).strip().upper()).first()
        if assignee:
            primary_user = assignee
            all_assignee_users = [assignee]

    points = data.get('points')
    if points is not None and points != '':
        try:
            points = int(points)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Story points must be a number.'}), 400
        if points < 0:
            return jsonify({'ok': False, 'error': 'Story points cannot be negative.'}), 400
    else:
        points = 0

    last = db.session.query(db.func.max(Issue.number)).filter(Issue.project_id == project.id).scalar() or 999
    sprint = None
    if data.get('sprint'):
        sprint = Sprint.query.filter_by(number=int(data['sprint']), project_id=project.id).first()
    issue = Issue(
        project_id=project.id, number=last + 1, title=summary,
        issue_type=issue_type,
        type_color=ISSUE_TYPE_COLORS[issue_type],
        priority=priority,
        priority_color=PRIORITY_COLORS[priority],
        points=points,
        assignee_id=primary_user.id if primary_user else None,
        assignee_initials=primary_user.initials if primary_user else None,
        assignee_color=primary_user.color if primary_user else '#9ca3af',
        due_date=end_date,
        start_date=start_date,
        labels=list(dict.fromkeys(data.get('labels') or [])),
        status=status,
        description=data.get('description') or '',
        acceptance_criteria=data.get('acceptance_criteria') or '',
        reporter_id=login_current_user.id if login_current_user.is_authenticated else 1,
        sprint_id=sprint.id if sprint else None,
    )
    db.session.add(issue)
    db.session.flush()

    for user in all_assignee_users:
        existing = IssueAssignees.query.filter_by(issue_id=issue.id, user_id=user.id).first()
        if not existing:
            db.session.add(IssueAssignees(issue_id=issue.id, user_id=user.id))

    db.session.commit()
    return jsonify(issue_dict(issue)), 201


@app.route('/api/issues/<int:issue_id>', methods=['PATCH'])
def api_update_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    if 'assignee' in data:
        u = User.query.filter_by(initials=data['assignee'].upper()).first() if data.get('assignee') else None
        issue.assignee_id = u.id if u else None
        issue.assignee_initials = u.initials if u else None
        issue.assignee_color = u.color if u else '#9ca3af'
        IssueAssignees.query.filter_by(issue_id=issue.id).delete()
        if u:
            db.session.add(IssueAssignees(issue_id=issue.id, user_id=u.id))
    if 'priority' in data:
        if data['priority'] not in PRIORITY_COLORS:
            return jsonify({'ok': False, 'error': 'Invalid priority.'}), 400
        issue.priority = data['priority']
        issue.priority_color = PRIORITY_COLORS[data['priority']]
    if 'title' in data:
        issue.title = data['title']
    if 'labels' in data:
        labels = data.get('labels') or []
        if isinstance(labels, str):
            labels = [x.strip() for x in labels.split(',') if x.strip()]
        issue.labels = [str(x) for x in labels]
    if 'status' in data:
        issue.status = data['status']
    if 'sprint_id' in data:
        new_sprint_id = data.get('sprint_id')
        if new_sprint_id is None or str(new_sprint_id).strip() in ('', '0', 'null'):
            issue.sprint_id = None
        else:
            try:
                sp_id = int(new_sprint_id)
            except (TypeError, ValueError):
                return jsonify({'ok': False, 'error': 'Invalid sprint.'}), 400
            sp = Sprint.query.filter(Sprint.id == sp_id,
                                     Sprint.project_id == issue.project_id).first()
            if not sp:
                return jsonify({'ok': False,
                                'error': 'Cannot assign an issue to a sprint from another project.'}), 400
            issue.sprint_id = sp.id
    if 'points' in data:
        issue.points = int(data.get('points') or 0)
    if 'due_date' in data:
        issue.due_date = data['due_date']
    if 'acceptance_criteria' in data:
        issue.acceptance_criteria = data['acceptance_criteria'] or ''
    db.session.commit()
    return jsonify(issue_dict(issue))


@app.route('/api/issues/<int:issue_id>/move', methods=['POST'])
def api_move_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    if 'status' in data:
        issue.status = data['status']
    if 'position' in data or 'sprint' in data:
        issue.position = int(data.get('position', issue.position))
        if 'sprint' in data and data.get('sprint'):
            sp = Sprint.query.filter(
                Sprint.number == int(data['sprint']),
                Sprint.project_id == issue.project_id,
            ).first()
            issue.sprint_id = sp.id if sp else issue.sprint_id
    db.session.commit()
    return jsonify({"ok": True, "issue": issue_dict(issue)})


@app.route('/api/issues/<int:issue_id>', methods=['DELETE'])
def api_delete_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    Comment.query.filter_by(issue_id=issue.id).delete()
    db.session.delete(issue)
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/api/comments', methods=['POST'])
def api_add_comment():
    data = request.get_json(silent=True) or {}
    issue = Issue.query.get(int(data.get('issue_id') or 0)) or Issue.query.first()
    author = User.query.filter_by(name=data.get('author', 'Alex Morgan')).first() or User.query.first()
    c = Comment(issue_id=issue.id, author_id=author.id, body=data.get('body', ''))
    db.session.add(c)
    db.session.commit()
    return jsonify({'id': c.id, 'body': c.body, 'author': author.name,
                    'author_initials': author.initials, 'author_color': author.color,
                    'created_at': c.created_at}), 201


@app.route('/api/notifications')
def api_notifications():
    return jsonify([{'id': n.id, 'icon': n.icon, 'color': n.color, 'title': n.title,
                     'detail': n.detail, 'type': n.notification_type, 'read': n.is_read,
                     'time': n.created_at}
                    for n in Notification.query.order_by(Notification.id.desc()).all()])


@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
def api_notification_read(nid):
    n = Notification.query.get_or_404(nid)
    n.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def api_delete_user(user_id):
    if login_current_user.plan != 'pro':
        abort(403)
    target = User.query.get_or_404(user_id)
    if target.id == login_current_user.id:
        return jsonify({"ok": False, "error": "You cannot delete your own account."}), 400

    data = request.get_json(silent=True) or {}
    confirm_email = (data.get('confirm_email') or '').strip().lower()
    if confirm_email != target.email.lower():
        return jsonify({"ok": False, "error": "Email confirmation does not match."}), 400

    from models import ProjectMembers
    ProjectMembers.query.filter_by(user_id=target.id).delete()
    IssueAssignees.query.filter_by(user_id=target.id).delete()
    Comment.query.filter_by(author_id=target.id).delete()

    assigned = [i for i in Issue.query.filter_by(assignee_id=target.id).all()]
    for i in assigned:
        i.assignee_id = None
        i.assignee_initials = None
        i.assignee_color = '#9ca3af'
        i.reporter_id = None if i.reporter_id == target.id else i.reporter_id

    for i in Issue.query.filter_by(reporter_id=target.id).all():
        if i.assignee_id != target.id:
            i.reporter_id = None

    Project.query.filter_by(lead_id=target.id).update({Project.lead_id: None, Project.lead_initials: None})

    db.session.delete(target)
    db.session.commit()
    return jsonify({"ok": True})


@app.route('/api/users', methods=['POST'])
@login_required
def api_create_user():
    if login_current_user.plan != 'pro':
        abort(403)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    role = (data.get('role') or '').strip()
    plan = (data.get('plan') or 'lite').strip().lower()
    team = (data.get('team') or 'General').strip()
    user_status = (data.get('status') or 'Active').strip()

    if not name:
        return jsonify({"ok": False, "error": "Name is required."}), 400
    if not email or '@' not in email:
        return jsonify({"ok": False, "error": "A valid email is required."}), 400
    if not password or len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters."}), 400
    if not role:
        return jsonify({"ok": False, "error": "Role is required."}), 400
    if plan not in ('pro', 'plus', 'lite'):
        return jsonify({"ok": False, "error": "Invalid plan."}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "error": "A user with that email already exists."}), 400

    initials = ''.join(p[0] for p in name.split() if p)[:2].upper() or 'XX'
    colors = ['#4f46e5', '#0891b2', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0d9488', '#db2777']
    color = random.choice(colors)

    u = User(name=name, initials=initials, email=email, role=role, plan=plan, team=team,
             capacity=50, active_projects=0, current_tasks=0, color=color, status=user_status)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return jsonify(user_dict(u)), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def api_update_user(user_id):
    if login_current_user.plan != 'pro':
        abort(403)
    target = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({"ok": False, "error": "Name is required."}), 400
        target.name = name
        target.initials = ''.join(p[0] for p in name.split() if p)[:2].upper() or target.initials

    if 'email' in data:
        email = (data['email'] or '').strip().lower()
        if not email or '@' not in email:
            return jsonify({"ok": False, "error": "A valid email is required."}), 400
        existing = User.query.filter(User.email == email, User.id != user_id).first()
        if existing:
            return jsonify({"ok": False, "error": "A user with that email already exists."}), 400
        target.email = email

    if 'role' in data:
        target.role = (data['role'] or '').strip() or target.role
    if 'plan' in data:
        p = (data['plan'] or '').strip().lower()
        if p in ('pro', 'plus', 'lite'):
            target.plan = p
    if 'team' in data:
        target.team = (data['team'] or '').strip() or target.team
    if 'capacity' in data:
        target.capacity = max(0, min(100, int(data.get('capacity') or 70)))
    if 'status' in data:
        target.status = (data['status'] or '').strip() or target.status

    target.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(user_dict(target))


@app.route('/api/users')
@login_required
def api_users():
    q = request.args.get('q', '').strip().lower()
    plan_filter = request.args.get('plan', '').strip().lower()
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip().lower()
    team_filter = request.args.get('team', '').strip()

    users_q = User.query
    if plan_filter and plan_filter in ('pro', 'plus', 'lite'):
        users_q = users_q.filter(User.plan == plan_filter)
    if role_filter:
        users_q = users_q.filter(User.role == role_filter)
    if team_filter:
        users_q = users_q.filter(User.team == team_filter)

    all_users = users_q.order_by(User.name).all()

    if q:
        all_users = [u for u in all_users if q in (u.name or '').lower()
                     or q in (u.email or '').lower()
                     or q in (u.team or '').lower()
                     or q in (u.role or '').lower()]

    now = datetime.utcnow()
    if status_filter == 'online':
        all_users = [u for u in all_users if u.last_seen and (now - u.last_seen) < timedelta(minutes=5)]
    elif status_filter == 'offline':
        all_users = [u for u in all_users if not u.last_seen or (now - u.last_seen) >= timedelta(minutes=5)]

    return jsonify([user_dict(u) for u in all_users])


@app.route('/api/projects', methods=['POST'])
@login_required
def api_create_project():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Project name is required.'}), 400
    if len(name) > 160:
        return jsonify({'ok': False, 'error': 'Project name is too long.'}), 400
    start_date = data.get('start_date')
    end_date = data.get('target_date') or data.get('due_date')
    if not start_date:
        return jsonify({'ok': False, 'error': 'Start date is required.'}), 400
    if not end_date:
        return jsonify({'ok': False, 'error': 'Target date is required.'}), 400
    ok, err = validate_project_dates(start_date, end_date)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400

    manager = data.get('manager') or data.get('manager_id')
    if isinstance(manager, str):
        manager = manager.strip()
    manager_user = None
    if isinstance(manager, int) or (isinstance(manager, str) and manager.isdigit()):
        manager_user = User.query.get(int(manager))
    elif manager:
        manager_user = User.query.filter_by(initials=str(manager).upper()).first()
    if not manager_user:
        return jsonify({'ok': False, 'error': 'Assignee is required and must be a valid user.'}), 400
    if manager_user.status and manager_user.status.lower() != 'active':
        return jsonify({'ok': False, 'error': 'Assignee must be an active user.'}), 400

    assignee_ids = data.get('assignees') or data.get('team_members') or []
    if not isinstance(assignee_ids, list):
        return jsonify({'ok': False, 'error': 'Team members must be a list.'}), 400
    seen_ids = set()
    validated_users = []
    for uid in assignee_ids:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid team member ID.'}), 400
        if uid_int in seen_ids:
            return jsonify({'ok': False, 'error': 'Duplicate team member IDs are not allowed.'}), 400
        seen_ids.add(uid_int)
        user = User.query.get(uid_int)
        if not user:
            return jsonify({'ok': False, 'error': f'Team member user ID {uid_int} does not exist.'}), 400
        validated_users.append(user)

    keys = [p.key for p in Project.query.all()]
    prefix = ''.join(ch for ch in name if ch.isalnum())[:3].upper() or 'PRJ'
    key = prefix
    n = 1
    while key in keys:
        n += 1
        key = f'{prefix}{n}'

    color = '#4f46e5'
    project = Project(
        key=key, name=name,
        description=(data.get('description') or ''),
        lead_id=manager_user.id,
        lead_initials=manager_user.initials,
        color=color,
        status='Not Started',
        start_date=format_date(start_date),
        due_date=format_date(end_date),
        progress=0,
    )
    db.session.add(project)
    db.session.flush()

    if validated_users:
        for user in validated_users:
            existing = ProjectMembers.query.filter_by(project_id=project.id, user_id=user.id).first()
            if not existing:
                db.session.add(ProjectMembers(project_id=project.id, user_id=user.id))

    db.session.commit()
    return jsonify(project_dict(project)), 201


@app.route('/api/sprints')
@login_required
def api_sprints():
    project = context_project(request.args.get('project'))
    return jsonify([sprint_api_dict(sp, context_issues(project)) for sp in context_sprints(project)])


def sprint_api_dict(sprint, issues):
    stats = sprint_stats_dict(sprint, issues)
    sp_issues = [i for i in issues if i.sprint_id == sprint.id]
    return {
        'id': sprint.id,
        'number': sprint.number,
        'name': sprint.name,
        'project': sprint.project.key if sprint.project else None,
        'project_id': sprint.project_id,
        'status': sprint.status,
        'start_date': format_date(sprint.start_date),
        'end_date': format_date(sprint.end_date),
        'goal': sprint.goal,
        'description': sprint.description or '',
        'to_do': stats['to_do'],
        'in_progress': stats['in_progress'],
        'in_review': stats['in_review'],
        'done': stats['done'],
        'backlog': stats['backlog'],
        'total': stats['total'],
        'remaining': stats['remaining'],
        'progress': stats['progress'],
        'story_points_total': stats['story_points_total'],
        'story_points_done': stats['story_points_done'],
        'tasks': [issue_dict(i) for i in sp_issues],
    }


@app.route('/api/sprints', methods=['POST'])
@login_required
def api_create_sprint():
    data = request.get_json(silent=True) or {}

    project_key = str(data.get('project') or '').strip().upper()
    project = Project.query.filter_by(key=project_key).first()
    if not project:
        return jsonify({'ok': False, 'error': 'Project is required.',
                        'field': 'project'}), 400

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Sprint name is required.',
                        'field': 'name'}), 400
    if len(name) > 80:
        return jsonify({'ok': False, 'error': 'Sprint name must be 80 characters or fewer.',
                        'field': 'name'}), 400
    existing = Sprint.query.filter(Sprint.project_id == project.id,
                                   db.func.lower(Sprint.name) == name.lower()).first()
    if existing:
        return jsonify({'ok': False,
                        'error': 'A sprint with this name already exists in this project.',
                        'field': 'name'}), 409

    start_date = data.get('start_date')
    end_date = data.get('end_date') or data.get('target_date')
    if not start_date:
        return jsonify({'ok': False, 'error': 'Start date is required.',
                        'field': 'start_date'}), 400
    if not end_date:
        return jsonify({'ok': False, 'error': 'End date is required.',
                        'field': 'end_date'}), 400
    if not validate_sprint_dates(start_date, end_date):
        return jsonify({'ok': False, 'error': 'End date must be after the start date.',
                        'field': 'end_date'}), 400

    requested_task_ids = data.get('task_ids') or data.get('tasks') or []
    if not isinstance(requested_task_ids, list):
        return jsonify({'ok': False, 'error': 'Tasks must be a list.',
                        'field': 'tasks'}), 400
    assigned_issues = []
    seen_task_ids = set()
    for tid in requested_task_ids:
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': f'Invalid task ID {tid}.',
                            'field': 'tasks'}), 400
        if tid_int in seen_task_ids:
            continue
        seen_task_ids.add(tid_int)
        issue = Issue.query.get(tid_int)
        if not issue:
            return jsonify({'ok': False, 'error': f'Task {tid_int} does not exist.',
                            'field': 'tasks'}), 400
        if issue.project_id != project.id:
            project_label = issue.project.key if issue.project else '?'
            return jsonify({'ok': False,
                            'error': f'Task {project_label}-{issue.number} does not belong to this project.',
                            'field': 'tasks'}), 400
        assigned_issues.append(issue)

    max_num = db.session.query(db.func.max(Sprint.number)).filter(Sprint.project_id == project.id).scalar() or 0
    sprint = Sprint(
        number=max_num + 1,
        name=name,
        project_id=project.id,
        start_date=format_date(start_date),
        end_date=format_date(end_date),
        goal=(data.get('goal') or '').strip()[:160],
        description=(data.get('description') or '').strip(),
        status='Planned',
        to_do=0,
        in_progress=0,
        in_review=0,
        done=0,
        story_points_total=0,
        story_points_done=0,
    )
    db.session.add(sprint)
    db.session.flush()

    for issue in assigned_issues:
        issue.sprint_id = sprint.id

    db.session.commit()
    return jsonify(sprint_api_dict(sprint, context_issues(project))), 201


@app.route('/api/sprints/<int:sprint_id>', methods=['PATCH'])
@login_required
def api_update_sprint(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    project = sprint.project
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Sprint name is required.',
                        'field': 'name'}), 400
    if len(name) > 80:
        return jsonify({'ok': False, 'error': 'Sprint name must be 80 characters or fewer.',
                        'field': 'name'}), 400
    existing = Sprint.query.filter(Sprint.project_id == project.id,
                                   Sprint.id != sprint.id,
                                   db.func.lower(Sprint.name) == name.lower()).first()
    if existing:
        return jsonify({'ok': False,
                        'error': 'A sprint with this name already exists in this project.',
                        'field': 'name'}), 409

    start_date = data.get('start_date')
    end_date = data.get('end_date') or data.get('target_date')
    if not start_date:
        return jsonify({'ok': False, 'error': 'Start date is required.',
                        'field': 'start_date'}), 400
    if not end_date:
        return jsonify({'ok': False, 'error': 'End date is required.',
                        'field': 'end_date'}), 400
    if not validate_sprint_dates(start_date, end_date):
        return jsonify({'ok': False, 'error': 'End date must be after the start date.',
                        'field': 'end_date'}), 400

    requested_task_ids = data.get('task_ids') or data.get('tasks') or []
    if not isinstance(requested_task_ids, list):
        return jsonify({'ok': False, 'error': 'Tasks must be a list.',
                        'field': 'tasks'}), 400
    assigned_issues = []
    seen_task_ids = set()
    for tid in requested_task_ids:
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': f'Invalid task ID {tid}.',
                            'field': 'tasks'}), 400
        if tid_int in seen_task_ids:
            continue
        seen_task_ids.add(tid_int)
        issue = Issue.query.get(tid_int)
        if not issue:
            return jsonify({'ok': False, 'error': f'Task {tid_int} does not exist.',
                            'field': 'tasks'}), 400
        if issue.project_id != project.id:
            project_label = issue.project.key if issue.project else '?'
            return jsonify({'ok': False,
                            'error': f'Task {project_label}-{issue.number} does not belong to this project.',
                            'field': 'tasks'}), 400
        assigned_issues.append(issue)

    for issue in context_issues(project):
        if issue.sprint_id == sprint.id and issue.id not in seen_task_ids:
            issue.sprint_id = None
    for issue in assigned_issues:
        issue.sprint_id = sprint.id

    sprint.name = name
    sprint.start_date = format_date(start_date)
    sprint.end_date = format_date(end_date)
    sprint.goal = (data.get('goal') or '').strip()[:160]
    sprint.description = (data.get('description') or '').strip()

    db.session.commit()
    return jsonify(sprint_api_dict(sprint, context_issues(project)))


def validate_sprint_dates(start_date, end_date):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start and end and end <= start:
        return False
    return True


@app.route('/api/sprints/<int:sprint_id>/start', methods=['POST'])
@login_required
def api_start_sprint(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    if sprint.status == 'Completed':
        return jsonify({'ok': False, 'error': 'Completed sprints cannot be restarted.'}), 409
    if sprint.status == 'Active':
        return jsonify(sprint_api_dict(sprint, context_issues(sprint.project))), 200

    active = Sprint.query.filter(Sprint.project_id == sprint.project_id,
                                 Sprint.status == 'Active',
                                 Sprint.id != sprint.id).first()
    if active:
        return jsonify({'ok': False,
                        'error': 'Another sprint is already active for this project. Complete the current sprint before starting a new one.',
                        'active_sprint': active.name}), 409

    sprint.status = 'Active'
    db.session.commit()
    return jsonify(sprint_api_dict(sprint, context_issues(sprint.project)))


@app.route('/api/sprints/<int:sprint_id>/complete', methods=['POST'])
@login_required
def api_complete_sprint(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    if sprint.status == 'Completed':
        return jsonify({'ok': False, 'error': 'This sprint is already completed.'}), 409
    if sprint.status != 'Active':
        return jsonify({'ok': False, 'error': 'Sprint must be started before it can be completed.'}), 409

    project = sprint.project
    issues = [i for i in context_issues(project) if i.sprint_id == sprint.id]
    incomplete = [i for i in issues if i.status != 'done']

    incomplete_action = ((request.get_json(silent=True) or {}).get('incomplete_action') or '').lower()

    if incomplete and incomplete_action not in ('backlog', 'next', 'keep'):
        return jsonify({
            'ok': False,
            'error': f'{len(incomplete)} issue(s) are still incomplete in this sprint.',
            'requires_decision': True,
            'incomplete_count': len(incomplete),
            'incomplete_action': 'Choose how to handle incomplete issues before completing the sprint.',
        }), 409

    if incomplete_action == 'backlog':
        for i in incomplete:
            i.sprint_id = None
            i.status = 'backlog'
    elif incomplete_action == 'next':
        next_sprint = Sprint.query.filter(Sprint.project_id == sprint.project_id,
                                          Sprint.status != 'Completed',
                                          Sprint.id != sprint.id).order_by(Sprint.number).first()
        if not next_sprint:
            return jsonify({'ok': False, 'error': 'No next sprint is available to move incomplete issues to.',
                            'requires_decision': True}), 409
        for i in incomplete:
            i.sprint_id = next_sprint.id

    sprint.status = 'Completed'
    db.session.commit()
    return jsonify(sprint_api_dict(sprint, context_issues(project)))


@app.route('/api/projects/<int:project_id>', methods=['PATCH'])
@login_required
def api_update_project(project_id):
    project = Project.query.get_or_404(project_id)
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'Project name is required.'}), 400
        project.name = name
    if 'description' in data:
        project.description = data.get('description') or ''
    if 'priority' in data:
        project.health_scope = (data.get('priority') or '')
    start_date = data.get('start_date', project.start_date)
    end_date = data.get('target_date', data.get('due_date', project.due_date))
    ok, err = validate_project_dates(start_date, end_date)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    if 'start_date' in data:
        project.start_date = data['start_date']
    if 'target_date' in data or 'due_date' in data:
        project.due_date = data.get('target_date', data.get('due_date'))
    if 'status' in data:
        project.status = data['status']
    db.session.commit()
    return jsonify(project_dict(project))


@app.route('/api/ai', methods=['POST'])
@login_required
def api_ai():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').lower()
    context = (data.get('context') or '').lower()
    me = login_current_user
    issues = Issue.query.all()
    active_sprint = Sprint.query.filter_by(status='Active').first()
    project = Project.query.first()

    def _overdue():
        out = []
        for i in issues:
            if i.status in ('done',):
                continue
            if i.due_date:
                out.append(i)
        out.sort(key=lambda x: x.due_date)
        return out[:5]

    if any(k in message or k in context for k in ('block', 'overdue', 'deadline')):
        od = _overdue()
        if not od:
            return jsonify({'type': 'text',
                            'response': "No overdue issues right now. The team's on track for this sprint."})
        lines = [f"- **{i.project.key}-{i.number}** {i.title} — due {i.due_date}, assigned to {i.assignee_initials or 'unassigned'}" for i in od]
        return jsonify({'type': 'task_list',
                        'response': "I found **" + str(len(od)) + "** issues with upcoming or missed deadlines:\n\n" + "\n".join(lines)})

    if 'sprint' in message:
        s = active_sprint or Sprint.query.order_by(Sprint.number).first()
        total = (s.story_points_total or 0) or 64
        done = (s.story_points_done or 0) or 46
        pct = round(done / total * 100) if total else 0
        return jsonify({
            'type': 'sprint_summary',
            'response': f"**{s.name}** is **{pct}% complete** with {done} of {total} story points delivered.\n\n"
                        f"● **{s.to_do}** to do\n● **{s.in_progress}** in progress\n● **{s.in_review}** in review\n● **{s.done}** done\n\n"
                        f"Sprint goal: _{s.goal}_"})

    if 'project' in message or 'e-commerce' in message or 'ecom' in message or 'summar' in message:
        return jsonify({
            'type': 'project_summary',
            'response': f"**{project.name}** is currently **{project.progress}% complete**.\n\n"
                        f"**{active_sprint.name if active_sprint else 'Sprint'}: {active_sprint.in_progress if active_sprint else 12} tasks in progress**, "
                        f"**{active_sprint.in_review if active_sprint else 7} in review**, "
                        f"**{active_sprint.done if active_sprint else 42} completed**.\n\n"
                        f"There are **4 high-priority issues** that need attention."})

    if 'task' in message or 'pending' in message or 'work' in message or 'overload' in message or 'who' in message:
        mine = [i for i in issues if i.assignee_initials == me.initials and i.status != 'done']
        busy = sorted(issues, key=lambda i: i.project_id)[:0]
        workloads = sorted(User.query.all(), key=lambda u: u.capacity, reverse=True)[:3]
        lines = [f"- **{u.initials}** {u.name} — {u.capacity}% capacity, {u.current_tasks} active tasks" for u in workloads]
        if mine:
            mine_lines = "\n".join(f"- **{i.project.key}-{i.number}** {i.title} — {i.status} · due {i.due_date}" for i in mine[:6])
        else:
            mine_lines = "- Nothing pending. Enjoy the calm!"
        return jsonify({'type': 'task_list',
                        'response': f"You have **{len(mine)}** pending tasks:\n\n{mine_lines}\n\n**Heaviest workloads this week:**\n\n" + "\n".join(lines)})

    if 'priority' in message or 'bug' in message:
        crit = [i for i in issues if i.priority in ('High', 'Critical') and i.status != 'done']
        lines = [f"- **{i.project.key}-{i.number}** {i.title} — **{i.priority}** · {i.status}" for i in crit[:6]]
        return jsonify({'type': 'task_list',
                        'response': f"Here are the **{len(crit)}** high-priority issues across all projects:\n\n" + "\n".join(lines)})

    if 'create' in message:
        return jsonify({'type': 'action',
                        'response': "I'd be happy to help create a task. Tell me the **title**, **project**, and **priority**, and I'll draft it for your review."})

    return jsonify({
        'type': 'text',
        'response': "I'm your ABC assistant. I can answer questions about **project status**, **sprint progress**, **team workload**, **overdue tasks**, and **high-priority issues**. Try asking:\n\n- \"What's the status of Sprint 12?\"\n- \"Which issues are overdue?\"\n- \"Who is overloaded this week?\"\n- \"Show high-priority bugs\""})


@app.context_processor
def inject_globals():
    cu = login_current_user if login_current_user.is_authenticated else None
    auth_pages = ('login', 'register', 'static')
    show_project = request.endpoint not in auth_pages and cu is not None
    return {
        'current_user': cu,
        'project': context_project() if show_project else (Project.query.first() if request.endpoint in ('login', 'register') else None),
        'projects_list': Project.query.all() if cu else [],
    }


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        try:
            inspector = sa_inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('users')]
            if 'last_seen' not in columns:
                db.session.execute(sa_text('ALTER TABLE users ADD COLUMN last_seen TIMESTAMP'))
                db.session.commit()
            if 'created_at' not in columns:
                db.session.execute(sa_text('ALTER TABLE users ADD COLUMN created_at TIMESTAMP'))
                db.session.commit()
            if 'updated_at' not in columns:
                db.session.execute(sa_text('ALTER TABLE users ADD COLUMN updated_at TIMESTAMP'))
                db.session.commit()
            issue_cols = [col['name'] for col in inspector.get_columns('issues')]
            if 'start_date' not in issue_cols:
                db.session.execute(sa_text("ALTER TABLE issues ADD COLUMN start_date VARCHAR(40)"))
                db.session.commit()
            sprint_cols = [col['name'] for col in inspector.get_columns('sprints')]
            if 'description' not in sprint_cols:
                db.session.execute(sa_text("ALTER TABLE sprints ADD COLUMN description TEXT"))
                db.session.commit()
        except Exception:
            pass
    app.run(
        debug=Config.DEBUG,
        host=Config.HOST,
        port=Config.PORT,
    )