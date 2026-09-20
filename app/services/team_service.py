"""Team / user management business logic (manager-gated at the route layer)."""
import random
import re
import secrets
from datetime import datetime

from app.extensions import db
from app.models import (
    Comment,
    Issue,
    IssueAssignees,
    Notification,
    Project,
    ProjectMembers,
    User,
    UserNotificationPreferences,
)
from app.utils.helpers import ensure_settings_for_user, member_counts, user_dict

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$')
_VALID_STATUSES = ('Active', 'Inactive')


def list_users(args):
    q = args.get('q', '').strip().lower()
    plan_filter = args.get('plan', '').strip().lower()
    role_filter = args.get('role', '').strip()
    status_filter = args.get('status', '').strip().lower()
    team_filter = args.get('team', '').strip()

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
        all_users = [u for u in all_users if u.last_seen and (now - u.last_seen).total_seconds() < 300]
    elif status_filter == 'offline':
        all_users = [u for u in all_users if not u.last_seen or (now - u.last_seen).total_seconds() >= 300]

    counts = member_counts()
    return [user_dict(u, counts.get(u.id)) for u in all_users]


def get_user(user_id):
    user = User.query.get_or_404(user_id)
    counts = member_counts([user.id]).get(user.id, {'projects': 0, 'tasks': 0})
    return user_dict(user, counts)


def create_user(data):
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    role = (data.get('role') or '').strip()
    plan = (data.get('plan') or 'lite').strip().lower()
    team = (data.get('team') or 'General').strip()
    user_status = (data.get('status') or 'Active').strip()

    if not name:
        return {"ok": False, "error": "Name is required."}, 400
    if not email or not _EMAIL_RE.match(email):
        return {"ok": False, "error": "A valid email is required."}, 400
    if not role:
        return {"ok": False, "error": "Role is required."}, 400
    if plan not in ('pro', 'plus', 'lite'):
        return {"ok": False, "error": "Invalid plan."}, 400
    if user_status not in _VALID_STATUSES:
        user_status = 'Active'

    if User.query.filter_by(email=email).first():
        return {"ok": False, "error": "A user with that email already exists."}, 409

    if not password:
        # The Add Team Member form has no password field; generate a random
        # credential so new members can sign in (details are out of band).
        password = secrets.token_urlsafe(12)

    initials = ''.join(p[0] for p in name.split() if p)[:2].upper() or 'XX'
    colors = ['#4f46e5', '#0891b2', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0d9488', '#db2777']
    color = random.choice(colors)

    u = User(name=name, initials=initials, email=email, role=role, plan=plan, team=team,
             capacity=50, active_projects=0, current_tasks=0, color=color, status=user_status)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    ensure_settings_for_user(u)
    db.session.commit()
    counts = member_counts([u.id]).get(u.id, {'projects': 0, 'tasks': 0})
    return user_dict(u, counts), 201


def update_user(user_id, data):
    target = User.query.get_or_404(user_id)

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return {"ok": False, "error": "Name is required."}, 400
        target.name = name
        target.initials = ''.join(p[0] for p in name.split() if p)[:2].upper() or target.initials

    if 'email' in data:
        email = (data['email'] or '').strip().lower()
        if not email or not _EMAIL_RE.match(email):
            return {"ok": False, "error": "A valid email is required."}, 400
        existing = User.query.filter(User.email == email, User.id != user_id).first()
        if existing:
            return {"ok": False, "error": "A user with that email already exists."}, 409
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
        status = (data['status'] or '').strip()
        if status not in _VALID_STATUSES:
            return {"ok": False, "error": "Status must be either Active or Inactive."}, 400
        target.status = status

    target.updated_at = datetime.utcnow()
    db.session.commit()
    counts = member_counts([target.id]).get(target.id, {'projects': 0, 'tasks': 0})
    return user_dict(target, counts), 200


def delete_user(user_id, data):
    if not data:
        data = {}
    target = User.query.get_or_404(user_id)

    confirm_email = (data.get('confirm_email') or '').strip().lower()
    if confirm_email != target.email.lower():
        return {"ok": False, "error": "Email confirmation does not match."}, 400

    ProjectMembers.query.filter_by(user_id=target.id).delete()
    IssueAssignees.query.filter_by(user_id=target.id).delete()
    Comment.query.filter_by(author_id=target.id).delete()
    UserNotificationPreferences.query.filter_by(user_id=target.id).delete()
    Notification.query.filter(
        db.or_(Notification.recipient_id == target.id,
               Notification.actor_id == target.id)).delete()

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
    return {"ok": True}, 200


def team_roles():
    """Distinct member roles for the Team page Role filter (driven by the DB)."""
    rows = (db.session.query(User.role, db.func.count(User.id).label('count'))
            .group_by(User.role).order_by(User.role).all())
    return [{'name': name, 'count': count} for name, count in rows]