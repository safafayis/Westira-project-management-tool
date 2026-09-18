"""All notification creation / queries.

Every notification is created through the helpers here (never from the
frontend). A deterministic ``event_key`` (unique per recipient) guarantees
duplicate prevention: re-running a creation for the same event returns the
existing row instead of inserting again.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    Comment,
    Issue,
    IssueAssignees,
    Notification,
    Project,
    ProjectMembers,
    Sprint,
    User,
)
from app.utils.helpers import (
    STATUS_LABELS,
    _display_time,
    _notification_pref_enabled,
    _notification_url,
    comment_preview,
    issue_ref,
    parse_any_date,
)

TYPE_META = {
    'issue_assigned':      {'icon': 'user-plus',     'color': '#4f46e5', 'category': 'assigned', 'priority': 'important'},
    'issue_reassigned':    {'icon': 'user-cog',      'color': '#7c3aed', 'category': 'assigned', 'priority': 'important'},
    'mention':             {'icon': 'at-sign',       'color': '#059669', 'category': 'mentions', 'priority': 'normal'},
    'comment':             {'icon': 'message-square','color': '#2563eb', 'category': 'updates',  'priority': 'normal'},
    'reply':               {'icon': 'message-circle','color': '#7c3aed', 'category': 'mentions', 'priority': 'normal'},
    'status_changed':      {'icon': 'git-merge',     'color': '#0891b2', 'category': 'updates',  'priority': 'normal'},
    'issue_completed':     {'icon': 'check-circle-2','color': '#059669', 'category': 'updates',  'priority': 'normal'},
    'priority_changed':    {'icon': 'flag',          'color': '#d97706', 'category': 'updates',  'priority': 'important'},
    'due_date_changed':    {'icon': 'calendar-clock','color': '#d97706', 'category': 'updates',  'priority': 'important'},
    'due_soon':            {'icon': 'clock',         'color': '#d97706', 'category': 'updates',  'priority': 'important'},
    'overdue':             {'icon': 'alert-triangle','color': '#dc2626', 'category': 'updates',  'priority': 'urgent'},
    'sprint_started':      {'icon': 'play',          'color': '#4f46e5', 'category': 'updates',  'priority': 'normal'},
    'sprint_ending':       {'icon': 'timer',         'color': '#d97706', 'category': 'updates',  'priority': 'important'},
    'sprint_completed':    {'icon': 'check-circle-2','color': '#059669', 'category': 'updates',  'priority': 'normal'},
    'project_added':       {'icon': 'folder-plus',   'color': '#4f46e5', 'category': 'updates',  'priority': 'normal'},
    'project_updated':     {'icon': 'folder-sync',   'color': '#0891b2', 'category': 'updates',  'priority': 'normal'},
}


# ------------------------------------------------------------------
# Core creation (with duplicate prevention)
# ------------------------------------------------------------------
def create_notification(*, recipient, ntype, title, message='', detail='',
                        actor=None, project=None, issue=None, sprint=None,
                        priority=None, event_key=None, meta=None):
    if recipient is None:
        return None
    if not _notification_pref_enabled(recipient, ntype):
        return None
    if event_key:
        existing = Notification.query.filter_by(recipient_id=recipient.id,
                                                event_key=event_key).first()
        if existing:
            return existing
    type_meta = TYPE_META.get(ntype, {})
    notification = Notification(
        recipient_id=recipient.id,
        actor_id=actor.id if actor else None,
        project_id=project.id if project else None,
        issue_id=issue.id if issue else None,
        sprint_id=sprint.id if sprint else None,
        type=ntype,
        category=type_meta.get('category', 'updates'),
        priority=priority or type_meta.get('priority', 'normal'),
        icon=type_meta.get('icon', 'bell'),
        color=type_meta.get('color', '#4f46e5'),
        title=title,
        message=message,
        detail=detail,
        event_key=event_key,
        meta=meta,
        created_dt=datetime.utcnow(),
        created_at=datetime.utcnow().strftime('%b %d, %Y'),
    )
    db.session.add(notification)
    return notification


def _notify_recipients(rows, actor):
    seen = set()
    for user in rows:
        if user is None or user.id is None:
            continue
        if actor and user.id == actor.id:
            continue
        if user.id in seen:
            continue
        seen.add(user.id)
        yield user


# ------------------------------------------------------------------
# Assignments
# ------------------------------------------------------------------
def create_assignment_notification(issue, actor, reassigned=False):
    """Notify assignees that a task was assigned/reassigned to them."""
    recipient_ids = set()
    if issue.assignee_id:
        recipient_ids.add(issue.assignee_id)
    for link in issue.assignee_links or []:
        recipient_ids.add(link.user_id)
    for uid in recipient_ids:
        recipient = User.query.get(uid)
        if not recipient:
            continue
        if actor and recipient.id == actor.id:
            continue
        key = issue_ref(issue)
        title = (f'{actor.name} reassigned {key} to you' if reassigned
                 else f'{actor.name} assigned {key} to you')
        if not actor:
            title = f'{key} was {"reassigned" if reassigned else "assigned"} to you'
        event_key = f'{key}:assign:{reassigned}:r{recipient.id}'
        ntype = 'issue_reassigned' if reassigned else 'issue_assigned'
        create_notification(recipient=recipient, ntype=ntype, title=title,
                            message=issue.title, detail=issue.title,
                            actor=actor, project=issue.project, issue=issue,
                            event_key=event_key)
    db.session.commit()


# ------------------------------------------------------------------
# Mentions / Comments
# ------------------------------------------------------------------
def detect_mentions(body, exclude_user_id=None):
    """Return users whose name/initials/email appear as @mention in a body."""
    if not body:
        return []
    text = ' ' + str(body).lower() + ' '
    found = []
    for user in User.query.all():
        if exclude_user_id and user.id == exclude_user_id:
            continue
        tokens = [user.name.lower()]
        if user.initials:
            tokens.append(user.initials.lower())
        if user.email:
            tokens.append(user.email.lower())
        for token in tokens:
            if token and ('@' + token) in text:
                found.append(user)
                break
    return found


def create_comment_notification(issue, comment, actor):
    """Comment, reply, and mention notifications for a new comment."""
    author = comment.author
    body = comment.body or ''
    mentioned = detect_mentions(body, exclude_user_id=author.id if author else None)

    for user in mentioned:
        key = issue_ref(issue)
        event_key = f'{key}:mention:{comment.id}:r{user.id}'
        create_notification(recipient=user, ntype='mention',
                            title=f'{author.name} mentioned you in {key}',
                            message=comment_preview(body),
                            actor=author, project=issue.project, issue=issue,
                            event_key=event_key,
                            meta={'comment_id': comment.id})

    recipients = set()
    if issue.assignee_id:
        recipients.add(issue.assignee_id)
    if issue.reporter_id:
        recipients.add(issue.reporter_id)
    for link in issue.assignee_links or []:
        recipients.add(link.user_id)

    prior_authors = {c.author_id for c in Comment.query
                     .filter_by(issue_id=issue.id)
                     .filter(Comment.id != comment.id)
                     .all() if c.author_id}

    for uid in recipients:
        if author and uid == author.id:
            continue
        if uid in {u.id for u in mentioned}:
            continue
        recipient = User.query.get(uid)
        if not recipient:
            continue
        key = issue_ref(issue)
        is_reply = uid in prior_authors
        event_key = f'{key}:{"reply" if is_reply else "comment"}:{comment.id}:r{uid}'
        if is_reply:
            ntype, title = 'reply', f'{author.name} replied to your comment'
        else:
            ntype = 'comment'
            title = f'{author.name} commented on {"your task" if uid == issue.assignee_id else key}'
        create_notification(recipient=recipient, ntype=ntype, title=title,
                            message=comment_preview(body),
                            actor=author, project=issue.project, issue=issue,
                            event_key=event_key,
                            meta={'comment_id': comment.id})
    db.session.commit()


def create_reply_notification(issue, recipient, actor, comment=None):
    """Reply notification for a prior comment author (kept for completeness)."""
    key = issue_ref(issue)
    event_key = f'{key}:reply:{comment.id}:r{recipient.id}' if comment else None
    create_notification(recipient=recipient, ntype='reply',
                        title=f'{actor.name} replied to your comment',
                        message=comment_preview(comment.body) if comment else '',
                        actor=actor, project=issue.project, issue=issue,
                        event_key=event_key)
    db.session.commit()


# ------------------------------------------------------------------
# Status updates
# ------------------------------------------------------------------
def create_status_notification(issue, actor):
    """Notify assignee(s) + reporter that a task status changed."""
    recipients = set()
    if issue.assignee_id:
        recipients.add(issue.assignee_id)
    if issue.reporter_id:
        recipients.add(issue.reporter_id)
    for link in issue.assignee_links or []:
        recipients.add(link.user_id)

    key = issue_ref(issue)
    done = issue.status == 'done'
    label = STATUS_LABELS.get(issue.status, (issue.status or '').title())
    ntype = 'issue_completed' if done else 'status_changed'
    title = f'{key} was completed' if done else f'{key} moved to {label}'

    for uid in recipients:
        if actor and uid == actor.id:
            continue
        recipient = User.query.get(uid)
        if not recipient:
            continue
        event_key = f'{key}:status:{issue.status}:r{uid}'
        create_notification(recipient=recipient, ntype=ntype, title=title,
                            message=issue.title, detail=issue.title,
                            actor=actor, project=issue.project, issue=issue,
                            event_key=event_key)
    db.session.commit()


def create_priority_change_notification(issue, actor):
    """Notify assignee(s) + reporter that priority changed."""
    recipients = set()
    if issue.assignee_id:
        recipients.add(issue.assignee_id)
    if issue.reporter_id:
        recipients.add(issue.reporter_id)
    for link in issue.assignee_links or []:
        recipients.add(link.user_id)

    key = issue_ref(issue)
    title = f'{key} priority changed to {issue.priority}'
    for uid in recipients:
        if actor and uid == actor.id:
            continue
        recipient = User.query.get(uid)
        if not recipient:
            continue
        event_key = f'{key}:priority:{issue.priority}:r{uid}'
        create_notification(recipient=recipient, ntype='priority_changed',
                            title=title, message=issue.title, detail=issue.title,
                            actor=actor, project=issue.project, issue=issue,
                            event_key=event_key)
    db.session.commit()


def create_due_date_change_notification(issue, actor):
    """Notify assignee(s) + reporter that the due date changed."""
    recipients = set()
    if issue.assignee_id:
        recipients.add(issue.assignee_id)
    if issue.reporter_id:
        recipients.add(issue.reporter_id)
    for link in issue.assignee_links or []:
        recipients.add(link.user_id)

    key = issue_ref(issue)
    title = f'Due date for {key} changed to {issue.due_date or "None"}'
    for uid in recipients:
        if actor and uid == actor.id:
            continue
        recipient = User.query.get(uid)
        if not recipient:
            continue
        event_key = f'{key}:due:{issue.due_date or "none"}:r{uid}'
        create_notification(recipient=recipient, ntype='due_date_changed',
                            title=title, message=issue.title, detail=issue.title,
                            actor=actor, project=issue.project, issue=issue,
                            event_key=event_key)
    db.session.commit()


# ------------------------------------------------------------------
# Due-date / deadline reminders
# ------------------------------------------------------------------
def create_due_soon_notification(issue, recipient, days, actor=None):
    key = issue_ref(issue)
    when = 'tomorrow' if days == 1 else f'in {days} days'
    title = f'{key} is due {when}'
    event_key = f'{key}:due_soon:{issue.due_date}:r{recipient.id}'
    return create_notification(recipient=recipient, ntype='due_soon', title=title,
                               message=issue.title, detail=issue.title,
                               actor=actor, project=issue.project, issue=issue,
                               event_key=event_key)


def create_overdue_notification(issue, recipient, actor=None):
    key = issue_ref(issue)
    title = f'{key} is overdue'
    event_key = f'{key}:overdue:{issue.due_date}:r{recipient.id}'
    return create_notification(recipient=recipient, ntype='overdue', title=title,
                               message=issue.title, detail=issue.title,
                               actor=actor, project=issue.project, issue=issue,
                               event_key=event_key)


# ------------------------------------------------------------------
# Sprint updates
# ------------------------------------------------------------------
def _sprint_project_members(sprint):
    rows = (db.session.query(User)
            .join(ProjectMembers, ProjectMembers.user_id == User.id)
            .filter(ProjectMembers.project_id == sprint.project_id)
            .all())
    return [u for u in rows if u and u.id]


def create_sprint_started_notification(sprint, actor=None):
    event_key = f'sprint:{sprint.id}:started'
    for user in _sprint_project_members(sprint):
        if actor and user.id == actor.id:
            continue
        create_notification(recipient=user, ntype='sprint_started',
                            title=f'{sprint.name} has started',
                            message=sprint.goal or sprint.name,
                            actor=actor, project=sprint.project, sprint=sprint,
                            event_key=f'{event_key}:r{user.id}')
    db.session.commit()


def create_sprint_completed_notification(sprint, actor=None, incomplete=0):
    event_key = f'sprint:{sprint.id}:completed'
    suffix = f' · {incomplete} incomplete task(s)' if incomplete else ''
    for user in _sprint_project_members(sprint):
        if actor and user.id == actor.id:
            continue
        create_notification(recipient=user, ntype='sprint_completed',
                            title=f'{sprint.name} was completed{suffix}',
                            message=sprint.goal or sprint.name,
                            actor=actor, project=sprint.project, sprint=sprint,
                            event_key=f'{event_key}:r{user.id}')
    db.session.commit()


def create_sprint_ending_notification(sprint, user, days, incomplete=0):
    when = 'tomorrow' if days == 1 else f'in {days} days'
    detail = ''
    if incomplete:
        detail = f' · You have {incomplete} incomplete task(s)'
    title = f'{sprint.name} ends {when}{detail}'
    event_key = f'sprint:{sprint.id}:ending:{sprint.end_date}:r{user.id}'
    create_notification(recipient=user, ntype='sprint_ending', title=title,
                        message=sprint.goal or sprint.name,
                        project=sprint.project, sprint=sprint,
                        event_key=event_key)
    db.session.commit()


# ------------------------------------------------------------------
# Project updates
# ------------------------------------------------------------------
def create_project_added_notification(project, recipient, actor=None):
    create_notification(recipient=recipient, ntype='project_added',
                        title=f'You were added to {project.name}',
                        message=project.description or project.key,
                        actor=actor, project=project,
                        event_key=f'project:{project.id}:added:r{recipient.id}')
    db.session.commit()


def create_project_updated_notification(project, actor=None):
    event_key = f'project:{project.id}:updated'
    for user in _project_members(project):
        if actor and user.id == actor.id:
            continue
        create_notification(recipient=user, ntype='project_updated',
                            title=f'Project {project.name} was updated',
                            message=project.status or project.key,
                            actor=actor, project=project,
                            event_key=f'{event_key}:r{user.id}')
    db.session.commit()


def _project_members(project):
    rows = (db.session.query(User)
            .join(ProjectMembers, ProjectMembers.user_id == User.id)
            .filter(ProjectMembers.project_id == project.id)
            .all())
    return [u for u in rows if u and u.id]


# ------------------------------------------------------------------
# Deadline / sprint-reminder sync (idempotent, event-key deduplicated)
# ------------------------------------------------------------------
def sync_user_reminders(user):
    """Generate due_soon / overdue / sprint_ending reminders for a user.

    Safe to call on every page load: deterministic event keys mean each
    reminder is created at most once per issue/due-date or sprint/end-date.
    """
    if user is None:
        return
    issues = _user_issues(user)
    today = datetime.utcnow().date()

    for issue in issues:
        if issue.status == 'done':
            continue
        due = parse_any_date(issue.due_date)
        if not due:
            continue
        due_date = due.date()
        if due_date < today:
            create_overdue_notification(issue, user)
        elif 0 < (due_date - today).days <= 3:
            create_due_soon_notification(issue, user, (due_date - today).days)

    for sprint in _user_sprints(user):
        end = parse_any_date(sprint.end_date)
        if not end:
            continue
        days = (end.date() - today).days
        if 0 <= days <= 3:
            incomplete = _sprint_incomplete(sprint, user)
            create_sprint_ending_notification(sprint, user, max(days, 0), incomplete)

    if db.session.new or db.session.dirty:
        db.session.commit()


def _user_issues(user):
    ids = {i.id for i in Issue.query.filter(Issue.assignee_id == user.id).all()}
    links = (db.session.query(IssueAssignees.issue_id)
             .filter(IssueAssignees.user_id == user.id).all())
    for (issue_id,) in links:
        ids.add(issue_id)
    return Issue.query.filter(Issue.id.in_(ids)).all() if ids else []


def _user_sprints(user):
    project_ids = [row for (row,) in
                   db.session.query(ProjectMembers.project_id)
                   .filter(ProjectMembers.user_id == user.id).all()]
    if not project_ids:
        return []
    return Sprint.query.filter(Sprint.project_id.in_(project_ids),
                               Sprint.status == 'Active').all()


def _sprint_incomplete(sprint, user):
    return Issue.query.filter(Issue.sprint_id == sprint.id,
                              Issue.status != 'done').count()


# ------------------------------------------------------------------
# Read / unread
# ------------------------------------------------------------------
def mark_as_read(notification):
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()


def mark_all_as_read(user):
    rows = (Notification.query
            .filter(Notification.recipient_id == user.id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None))
            .all())
    for row in rows:
        row.is_read = True
        row.read_at = datetime.utcnow()
    db.session.commit()
    return len(rows)


def unread_count(user):
    return (Notification.query
            .filter(Notification.recipient_id == user.id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None))
            .count())


def soft_delete(notification):
    notification.deleted_at = datetime.utcnow()
    db.session.commit()


# ------------------------------------------------------------------
# Notification serializer
# ------------------------------------------------------------------
def serialize(notification):
    actor = notification.actor
    project = notification.project
    issue = notification.issue
    sprint = notification.sprint
    return {
        'id': notification.id,
        'type': notification.type,
        'category': notification.category,
        'priority': notification.priority,
        'icon': notification.icon,
        'color': notification.color,
        'title': notification.title,
        'message': notification.message,
        'detail': notification.detail,
        'read': bool(notification.is_read),
        'time': _display_time(notification),
        'created_at': notification.created_at,
        'actor': {'id': actor.id, 'name': actor.name,
                  'initials': actor.initials, 'color': actor.color} if actor else None,
        'project': {'key': project.key, 'name': project.name} if project else None,
        'issue': {'id': issue.id, 'key': issue_ref(issue),
                  'title': issue.title} if issue else None,
        'sprint': {'number': sprint.number, 'name': sprint.name} if sprint else None,
        'url': _notification_url(notification),
    }


# ------------------------------------------------------------------
# Notifications list / read endpoints (service-side queries)
# ------------------------------------------------------------------
def list_notifications(user, args):
    """Paginated notification list for the current user."""
    sync_user_reminders(user)
    category = args.get('category', 'all')
    read_filter = args.get('read')
    search = args.get('q', '').strip()
    try:
        page = max(int(args.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        limit = min(int(args.get('limit', 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    q = Notification.query.filter(
        Notification.recipient_id == user.id,
        Notification.deleted_at.is_(None),
    )
    if category and category != 'all':
        q = q.filter(Notification.category == category)
    if read_filter is not None and read_filter != '':
        q = q.filter(Notification.is_read == (read_filter == 'true'))
    if search:
        like = f'%{search}%'
        q = q.filter(db.or_(
            Notification.title.ilike(like),
            Notification.message.ilike(like),
            Notification.detail.ilike(like),
        ))

    total = q.count()
    rows = (q.order_by(Notification.created_dt.desc().nullslast(), Notification.id.desc())
             .offset((page - 1) * limit).limit(limit).all())

    return {
        'notifications': [serialize(n) for n in rows],
        'pagination': {
            'page': page, 'limit': limit,
            'total': total, 'has_next': page * limit < total,
        },
    }


def unread_count_breakdown(user):
    """Unread count total plus category breakdown."""
    sync_user_reminders(user)
    total = unread_count(user)
    cats = (db.session.query(Notification.category, db.func.count(Notification.id))
            .filter(Notification.recipient_id == user.id,
                    Notification.is_read.is_(False),
                    Notification.deleted_at.is_(None))
            .group_by(Notification.category).all())
    counts = {cat: cnt for cat, cnt in cats}
    return {
        'count': total,
        'mentions': counts.get('mentions', 0),
        'assigned': counts.get('assigned', 0),
        'updates': counts.get('updates', 0),
    }