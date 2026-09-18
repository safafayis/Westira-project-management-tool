"""Issue + comment business logic."""
from datetime import datetime

from app.extensions import db
from app.models import (Comment, Issue, IssueAssignees, Notification, Project,
                        Sprint, User)
from app.services import notification_service
from app.utils.helpers import (
    ISSUE_TYPE_COLORS,
    KANBAN_STATUSES,
    PRIORITY_COLORS,
    issue_dict,
)
from app.utils.validators import validate_task_dates


# ------------------------------------------------------------------
# Reading
# ------------------------------------------------------------------
def list_issues(args):
    """List issues with the same filters the old monolith endpoint exposed."""
    q = Issue.query
    project = args.get('project')
    project_id = args.get('project_id')
    status = args.get('status')
    priority = args.get('priority')
    assignee = args.get('assignee')
    assignee_id = args.get('assignee_id')
    sprint = args.get('sprint')
    sprint_id = args.get('sprint_id')
    search = args.get('q')
    if project:
        q = q.join(Project).filter(Project.key == project.upper())
    if project_id:
        try:
            q = q.filter(Issue.project_id == int(project_id))
        except (TypeError, ValueError):
            return []
    if status:
        q = q.filter(Issue.status == status)
    if priority:
        q = q.filter(Issue.priority == priority)
    if assignee:
        users = [u for u in User.query.all() if u.initials == assignee.upper()]
        if not users:
            q = q.filter(False)
        else:
            user_ids = [u.id for u in users]
            in_join = db.select(IssueAssignees.issue_id).where(IssueAssignees.user_id.in_(user_ids))
            q = q.filter(db.or_(Issue.assignee_id.in_(user_ids), Issue.id.in_(in_join)))
    if assignee_id:
        try:
            user_ids = [int(assignee_id)]
        except (TypeError, ValueError):
            return []
        in_join = db.select(IssueAssignees.issue_id).where(IssueAssignees.user_id.in_(user_ids))
        q = q.filter(db.or_(Issue.assignee_id.in_(user_ids), Issue.id.in_(in_join)))
    if sprint:
        try:
            sprint_num = int(sprint)
        except (TypeError, ValueError):
            return []
        sp = Sprint.query.filter_by(number=sprint_num).first()
        if not sp:
            return []
        q = q.filter(Issue.sprint_id == sp.id)
    if sprint_id:
        try:
            q = q.filter(Issue.sprint_id == int(sprint_id))
        except (TypeError, ValueError):
            return []
    if search:
        term = f'%{search.strip().lower()}%'
        q = q.filter(db.or_(
            db.func.lower(Issue.title).like(term),
            db.cast(Issue.number, db.String).like(term),
            db.func.lower(db.func.coalesce(Issue.description, '')).like(term),
            db.func.lower(db.func.coalesce(db.cast(Issue.labels, db.Text), '')).like(term),
        ))
    return [issue_dict(i) for i in q.order_by(Issue.position).all()]


def get_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    return issue_dict(issue)


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------
def create_issue(data, actor):
    summary = (data.get('summary') or data.get('title') or '').strip()
    if not summary:
        return {'ok': False, 'error': 'Summary is required.'}, 400
    if len(summary) > 240:
        return {'ok': False, 'error': 'Summary must be 240 characters or fewer.'}, 400

    project = Project.query.filter_by(key=(data.get('project') or 'ECOM').upper()).first()
    if not project:
        return {'ok': False, 'error': 'Invalid project.'}, 400

    issue_type = data.get('issue_type') or 'Story'
    if issue_type not in ISSUE_TYPE_COLORS:
        return {'ok': False, 'error': 'Invalid issue type.'}, 400

    priority = data.get('priority') or 'Medium'
    if priority not in PRIORITY_COLORS:
        return {'ok': False, 'error': 'Invalid priority.'}, 400

    status = str(data.get('status') or 'backlog').strip().lower()
    if status not in KANBAN_STATUSES:
        return {'ok': False, 'error': 'Invalid status.'}, 400

    start_date = data.get('start_date')
    end_date = data.get('due_date') or data.get('end_date') or data.get('target_date')
    ok, err = validate_task_dates(project, start_date, end_date)
    if not ok:
        return {'ok': False, 'error': err}, 400

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
                return {'ok': False, 'error': f'Assignee user ID {uid_int} does not exist.'}, 400
            if user.status and user.status.lower() != 'active':
                return {'ok': False, 'error': f'Assignee {user.name} must be an active user.'}, 400
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
            return {'ok': False, 'error': 'Story points must be a number.'}, 400
        if points < 0:
            return {'ok': False, 'error': 'Story points cannot be negative.'}, 400
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
        reporter_id=actor.id if actor is not None else 1,
        sprint_id=sprint.id if sprint else None,
    )
    if status == 'done':
        issue.completed_at = datetime.utcnow()
    db.session.add(issue)
    db.session.flush()

    for user in all_assignee_users:
        existing = IssueAssignees.query.filter_by(issue_id=issue.id, user_id=user.id).first()
        if not existing:
            db.session.add(IssueAssignees(issue_id=issue.id, user_id=user.id))

    db.session.commit()
    try:
        notification_service.create_assignment_notification(issue, actor)
    except Exception:
        pass
    return issue_dict(issue), 201


# ------------------------------------------------------------------
# Update / move / delete
# ------------------------------------------------------------------
def update_issue(issue_id, data, actor):
    issue = Issue.query.get_or_404(issue_id)
    old_assignee_id = issue.assignee_id
    old_priority = issue.priority
    old_status = issue.status
    old_due_date = issue.due_date
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
            return {'ok': False, 'error': 'Invalid priority.'}, 400
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
        was_done = issue.status == 'done'
        issue.status = data['status']
        if data['status'] == 'done' and not was_done:
            issue.completed_at = datetime.utcnow()
        elif was_done and data['status'] != 'done':
            issue.completed_at = None
    if 'sprint_id' in data:
        new_sprint_id = data.get('sprint_id')
        if new_sprint_id is None or str(new_sprint_id).strip() in ('', '0', 'null'):
            issue.sprint_id = None
        else:
            try:
                sp_id = int(new_sprint_id)
            except (TypeError, ValueError):
                return {'ok': False, 'error': 'Invalid sprint.'}, 400
            sp = Sprint.query.filter(Sprint.id == sp_id,
                                     Sprint.project_id == issue.project_id).first()
            if not sp:
                return {'ok': False,
                        'error': 'Cannot assign an issue to a sprint from another project.'}, 400
            issue.sprint_id = sp.id
    if 'points' in data:
        issue.points = int(data.get('points') or 0)
    if 'due_date' in data:
        issue.due_date = data['due_date']
    if 'acceptance_criteria' in data:
        issue.acceptance_criteria = data['acceptance_criteria'] or ''
    db.session.commit()
    try:
        if 'assignee' in data and issue.assignee_id != old_assignee_id:
            notification_service.create_assignment_notification(issue, actor, reassigned=old_assignee_id is not None)
        if 'priority' in data and issue.priority != old_priority:
            notification_service.create_priority_change_notification(issue, actor)
        if 'due_date' in data and issue.due_date != old_due_date:
            notification_service.create_due_date_change_notification(issue, actor)
        if 'status' in data and issue.status != old_status:
            notification_service.create_status_notification(issue, actor)
    except Exception:
        pass
    return issue_dict(issue), 200


def move_issue(issue_id, data, actor):
    issue = Issue.query.get_or_404(issue_id)
    old_status = issue.status
    if 'status' in data:
        issue.status = data['status']
        if data['status'] == 'done' and old_status != 'done':
            issue.completed_at = datetime.utcnow()
        elif old_status == 'done' and data['status'] != 'done':
            issue.completed_at = None
    if 'position' in data or 'sprint' in data:
        issue.position = int(data.get('position', issue.position))
        if 'sprint' in data and data.get('sprint'):
            sp = Sprint.query.filter(
                Sprint.number == int(data['sprint']),
                Sprint.project_id == issue.project_id,
            ).first()
            issue.sprint_id = sp.id if sp else issue.sprint_id
    db.session.commit()
    try:
        if 'status' in data and issue.status != old_status:
            notification_service.create_status_notification(issue, actor)
    except Exception:
        pass
    return {"ok": True, "issue": issue_dict(issue)}


def delete_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    Comment.query.filter_by(issue_id=issue.id).delete()
    Notification.query.filter_by(issue_id=issue.id).delete()
    db.session.delete(issue)
    db.session.commit()
    return {"ok": True}


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------
def add_comment(data, actor):
    issue = Issue.query.get(int(data.get('issue_id') or 0))
    if not issue:
        return {'ok': False, 'error': 'Issue not found.'}, 404
    c = Comment(issue_id=issue.id, author_id=actor.id, body=data.get('body', ''))
    db.session.add(c)
    db.session.commit()
    try:
        notification_service.create_comment_notification(issue, c, actor)
    except Exception:
        pass
    return {'id': c.id, 'body': c.body, 'author': actor.name,
            'author_initials': actor.initials, 'author_color': actor.color,
            'created_at': c.created_at}, 201


def get_comment(comment_id):
    c = Comment.query.get_or_404(comment_id)
    author = User.query.get(c.author_id)
    return {'id': c.id, 'body': c.body, 'author_id': c.author_id,
            'author': author.name if author else None,
            'author_initials': author.initials if author else None,
            'author_color': author.color if author else None,
            'issue_id': c.issue_id,
            'created_at': c.created_at}


def update_comment(comment_id, data, actor):
    c = Comment.query.get_or_404(comment_id)
    body = (data.get('body') or '').strip()
    if not body:
        return {'ok': False, 'error': 'Comment body is required.'}, 400
    c.body = body
    db.session.commit()
    return {'id': c.id, 'body': c.body, 'author_id': c.author_id,
            'issue_id': c.issue_id, 'created_at': c.created_at}


def delete_comment(comment_id):
    c = Comment.query.get_or_404(comment_id)
    db.session.delete(c)
    db.session.commit()
    return {'ok': True}


def issue_comments(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    comments = Comment.query.filter_by(issue_id=issue.id).order_by(Comment.created_at).all()
    result = []
    for c in comments:
        author = User.query.get(c.author_id)
        result.append({
            'id': c.id, 'body': c.body, 'author_id': c.author_id,
            'author': author.name if author else None,
            'author_initials': author.initials if author else None,
            'author_color': author.color if author else None,
            'created_at': c.created_at,
        })
    return result