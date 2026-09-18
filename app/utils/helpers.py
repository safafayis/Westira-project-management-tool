"""Shared helpers: serializers, date utils, constants and workspace defaults.

Kept dependency-free of services so both API blueprints and the services
layer can import from here without circular imports.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    Issue,
    IssueAssignees,
    Project,
    Sprint,
    User,
    UserNotificationPreferences,
    WorkspaceSettings,
)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Context helpers (page rendering)
# ---------------------------------------------------------------------------

def context_project(key='ECOM'):
    return Project.query.filter_by(key=key).first() or Project.query.first()


def context_sprints(project):
    return Sprint.query.filter_by(project_id=project.id).order_by(Sprint.number).all()


def context_issues(project):
    return Issue.query.filter_by(project_id=project.id).order_by(Issue.position).all()


def context_sprint_stats(project):
    return [sprint_stats_dict(sp, context_issues(project)) for sp in context_sprints(project)]


# ---------------------------------------------------------------------------
# Date handling
# ---------------------------------------------------------------------------

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


DATE_FORMATS = ('%b %d, %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%b %d', '%d %b')


def parse_any_date(value):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
            if fmt in ('%b %d', '%d %b'):
                d = d.replace(year=datetime.utcnow().year)
            return d
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRIORITY_COLORS = {
    'Highest': '#dc2626', 'High': '#d97706', 'Medium': '#0891b2', 'Low': '#4f46e5', 'Lowest': '#6b7280',
    'Critical': '#dc2626',
}
ISSUE_TYPE_COLORS = {'Story': '#059669', 'Bug': '#dc2626', 'Task': '#4f46e5', 'Epic': '#7c3aed'}
KANBAN_STATUSES = ['backlog', 'todo', 'in_progress', 'in_review', 'done']

STATUS_LABELS = {
    'backlog': 'Backlog', 'todo': 'To Do', 'in_progress': 'In Progress',
    'in_review': 'In Review', 'done': 'Done',
}


# ---------------------------------------------------------------------------
# Issue helpers
# ---------------------------------------------------------------------------

def issue_ref(issue):
    if not issue:
        return 'task'
    project = issue.project
    key = f'{project.key}-{issue.number}' if project else f'Issue {issue.id}'
    return key


def comment_preview(body, limit=120):
    body = (body or '').replace('\r', ' ').replace('\n', ' ').strip()
    return body[:limit] + ('…' if len(body) > limit else '')


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def _display_time(notification):
    dt = notification.created_dt
    if not dt:
        return notification.created_at or ''
    diff = datetime.utcnow() - dt
    if diff < timedelta(seconds=60):
        return 'just now'
    if diff < timedelta(hours=1):
        return f'{int(diff.total_seconds() // 60)}m ago'
    if diff < timedelta(days=1):
        return f'{int(diff.total_seconds() // 3600)}h ago'
    if diff < timedelta(days=7):
        return f'{diff.days}d ago'
    return dt.strftime('%b %d, %Y')


def _notification_url(notification):
    if notification.issue_id:
        return f'/issue/{notification.issue_id}'
    if notification.sprint_id and notification.project_id:
        project = Project.query.get(notification.project_id)
        if project:
            return f'/sprints/{project.key}'
    if notification.project_id:
        project = Project.query.get(notification.project_id)
        if project:
            return f'/project/{project.key}'
    return ''


# Notification type -> preference key used to gate notification generation.
NOTIFICATION_PREF_KEYS = {
    'issue_assigned': 'assignments',
    'issue_reassigned': 'assignments',
    'mention': 'mentions',
    'reply': 'mentions',
    'comment': 'comments',
    'status_changed': 'status_changes',
    'issue_completed': 'status_changes',
    'priority_changed': 'status_changes',
    'due_date_changed': 'status_changes',
    'due_soon': 'due_date_reminders',
    'overdue': 'overdue',
    'sprint_started': 'sprint_updates',
    'sprint_ending': 'sprint_updates',
    'sprint_completed': 'sprint_updates',
    'project_added': 'project_updates',
    'project_updated': 'project_updates',
}


def _workspace_name():
    ws = WorkspaceSettings.query.get(1)
    return ws.name if ws else 'ABC'


def _notification_pref_enabled(recipient, ntype):
    if recipient is None:
        return True
    pref_key = NOTIFICATION_PREF_KEYS.get(ntype, 'system')
    prefs = UserNotificationPreferences.query.filter_by(user_id=recipient.id).first()
    if prefs is None:
        return True
    return bool(getattr(prefs, pref_key, True))


def ensure_settings_for_user(user):
    if not user.permission_role:
        user.permission_role = 'member'
    prefs = UserNotificationPreferences.query.filter_by(user_id=user.id).first()
    if prefs is None:
        db.session.add(UserNotificationPreferences(user_id=user.id))


def seed_settings_defaults():
    """Idempotent seed for workspace defaults (runs at startup).

    Safe to run on every boot: records are only inserted when missing, and
    default per-user settings are created for any user missing them.
    """
    if WorkspaceSettings.query.get(1) is None:
        db.session.add(WorkspaceSettings(id=1))

    for user in User.query.all():
        if not user.permission_role:
            user.permission_role = 'member'
        if UserNotificationPreferences.query.filter_by(user_id=user.id).first() is None:
            db.session.add(UserNotificationPreferences(user_id=user.id))
    db.session.commit()

    owner = User.query.filter_by(email='alex@abc.io').first()
    if owner and owner.permission_role != 'administrator':
        owner.permission_role = 'administrator'
        db.session.commit()