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
    Notification,
    Project,
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
    return {
        'id': i.id, 'project': i.project.key if i.project else 'ECOM',
        'number': i.number, 'key': f'{i.project.key}-{i.number}' if i.project else f'ECOM-{i.number}',
        'title': i.title, 'type': i.issue_type, 'type_color': i.type_color,
        'priority': i.priority, 'priority_color': i.priority_color, 'points': i.points,
        'assignee_id': i.assignee_id, 'assignee': i.assignee_initials,
        'assignee_color': i.assignee_color, 'due': i.due_date, 'labels': i.labels or [],
        'status': i.status, 'sprint': i.sprint.number if i.sprint else None,
        'description': i.description, 'acceptance_criteria': i.acceptance_criteria,
        'reporter': i.reporter_id, 'created': i.created_at,
    }


def context_project(key='ECOM'):
    return Project.query.filter_by(key=key).first() or Project.query.first()


def context_sprints(project):
    return Sprint.query.filter_by(project_id=project.id).order_by(Sprint.number).all()


def context_issues(project):
    return Issue.query.filter_by(project_id=project.id).order_by(Issue.position).all()


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
        flash('Account created. Welcome to Wexira!', 'success')
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

    active_projects = sum(1 for p in projects_all if p.status != 'Completed')
    open_issues = sum(1 for i in issues_all if i.status != 'done')
    tasks_due = sum(1 for i in issues_all if i.due_date and i.status != 'done')
    sprint_pct = round((active_sprint.story_points_done or 0) / (active_sprint.story_points_total or 1) * 100) if active_sprint else 0
    my_tasks = [i for i in issues_all if i.assignee_initials == me.initials][:6]

    kpis = [
        {'value': active_projects, 'label': 'Active Projects', 'trend': '+2', 'up': True,
         'icon': 'folder-kanban', 'color': '#4f46e5', 'bg': '#eef2ff'},
        {'value': open_issues, 'label': 'Open Issues', 'trend': '-4', 'up': False,
         'icon': 'alert-circle', 'color': '#0891b2', 'bg': '#ecfeff'},
        {'value': tasks_due, 'label': 'Tasks Due This Week', 'trend': '2 soon', 'up': True,
         'icon': 'calendar-clock', 'color': '#d97706', 'bg': '#fffbeb'},
        {'value': f'{sprint_pct}%', 'label': 'Sprint Progress', 'trend': '+12%', 'up': True,
         'icon': 'timer', 'color': '#7c3aed', 'bg': '#f5f3ff'},
        {'value': len(users_all), 'label': 'Team Members', 'trend': '+1', 'up': True,
         'icon': 'users', 'color': '#059669', 'bg': '#ecfdf5'},
    ]

    context = {
        'active_page': 'dashboard', 'kpis': kpis,
        'projects': projects_all, 'issues': issues_all,
        'active_sprint': active_sprint, 'my_tasks': my_tasks,
        'notifications': Notification.query.order_by(Notification.id.desc()).limit(4).all(),
        'activity': Activity.query.order_by(Activity.id.desc()).limit(8).all(),
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
    return render_template('projects.html', active_page='projects',
                           projects=Project.query.all())


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
                           issues=context_issues(project), all_issues=Issue.query.all())


@app.route('/sprints')
@login_required
def sprints(key='ECOM'):
    project = context_project(key)
    return render_template('sprints.html', active_page='sprints',
                           project=project, sprints=context_sprints(project),
                           issues=context_issues(project))


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
    my_tasks = [i for i in Issue.query.all() if i.assignee_initials == me.initials][:8]
    return render_template('my_work.html', active_page='my_work',
                           users=User.query.all(), all_issues=Issue.query.all(),
                           me=me, my_tasks=my_tasks)


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
    if project:
        q = q.join(Project).filter(Project.key == project.upper())
    if status:
        q = q.filter(Issue.status == status)
    if assignee:
        q = q.filter(Issue.assignee_initials == assignee.upper())
    if sprint:
        q = q.join(Sprint).filter(Sprint.number == int(sprint))
    return jsonify([issue_dict(i) for i in q.order_by(Issue.position).all()])


@app.route('/api/issues/<int:issue_id>')
def api_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    return jsonify(issue_dict(issue))


@app.route('/api/issues', methods=['POST'])
def api_create_issue():
    data = request.get_json(silent=True) or {}
    project = Project.query.filter_by(key=(data.get('project') or 'ECOM').upper()).first() or Project.query.first()
    last = db.session.query(db.func.max(Issue.number)).filter(Issue.project_id == project.id).scalar() or 999
    sprint = None
    if data.get('sprint'):
        sprint = Sprint.query.filter_by(number=int(data['sprint']), project_id=project.id).first()
    issue = Issue(
        project_id=project.id, number=last + 1, title=data.get('summary') or data.get('title') or 'Untitled',
        issue_type=data.get('issue_type') or 'Story',
        type_color={'Story': '#059669', 'Bug': '#dc2626', 'Task': '#4f46e5', 'Epic': '#7c3aed'}
                    .get(data.get('issue_type') or 'Story', '#059669'),
        priority=data.get('priority') or 'Medium',
        priority_color={'Low': '#4f46e5', 'Medium': '#0891b2', 'High': '#d97706', 'Critical': '#dc2626'}
                        .get(data.get('priority') or 'Medium', '#0891b2'),
        points=data.get('points') or 0,
        assignee_initials=data.get('assignee'),
        assignee_color='#9ca3af',
        due_date=data.get('due_date'),
        labels=data.get('labels') or [],
        status=data.get('status') or 'backlog',
        description=data.get('description') or '',
        reporter_id=1, sprint_id=sprint.id if sprint else None,
    )
    db.session.add(issue)
    db.session.commit()
    return jsonify(issue_dict(issue)), 201


@app.route('/api/issues/<int:issue_id>', methods=['PATCH'])
def api_update_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    data = request.get_json(silent=True) or {}
    if 'assignee' in data:
        u = User.query.filter_by(initials=data['assignee'].upper()).first()
        issue.assignee_id = u.id if u else None
        issue.assignee_initials = u.initials if u else None
        issue.assignee_color = u.color if u else '#9ca3af'
    if 'priority' in data:
        issue.priority = data['priority']
        issue.priority_color = {'Low': '#4f46e5', 'Medium': '#0891b2', 'High': '#d97706', 'Critical': '#dc2626'}[data['priority']]
    if 'title' in data:
        issue.title = data['title']
    if 'status' in data:
        issue.status = data['status']
    if 'points' in data:
        issue.points = int(data.get('points') or 0)
    if 'due_date' in data:
        issue.due_date = data['due_date']
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
        if data.get('sprint'):
            sp = Sprint.query.filter_by(number=int(data['sprint'])).first()
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
        'response': "I'm your Wexira assistant. I can answer questions about **project status**, **sprint progress**, **team workload**, **overdue tasks**, and **high-priority issues**. Try asking:\n\n- \"What's the status of Sprint 12?\"\n- \"Which issues are overdue?\"\n- \"Who is overloaded this week?\"\n- \"Show high-priority bugs\""})


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
        except Exception:
            pass
    app.run(
        debug=Config.DEBUG,
        host=Config.HOST,
        port=Config.PORT,
    )