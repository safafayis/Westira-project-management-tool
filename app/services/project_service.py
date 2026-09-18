"""Project business logic: CRUD, membership and notifications side-effects."""
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
from app.services import notification_service
from app.utils.helpers import format_date, project_dict, user_dict
from app.utils.validators import validate_project_dates


def list_projects(status=None, search=''):
    q = Project.query
    if status:
        q = q.filter(Project.status == status)
    if search:
        like = f'%{search}%'
        q = q.filter(db.or_(
            Project.name.ilike(like),
            Project.key.ilike(like),
        ))
    projects = q.order_by(Project.name).all()
    result = []
    for p in projects:
        d = project_dict(p)
        members = ProjectMembers.query.filter_by(project_id=p.id).all()
        member_users = [User.query.get(m.user_id) for m in members if User.query.get(m.user_id)]
        d['members'] = [user_dict(u) for u in member_users]
        d['member_count'] = len(member_users)
        issues = Issue.query.filter_by(project_id=p.id).all()
        d['total_issues'] = len(issues)
        d['done_issues'] = sum(1 for i in issues if i.status == 'done')
        result.append(d)
    return result


def get_project(project_id):
    project = Project.query.get_or_404(project_id)
    d = project_dict(project)
    members = ProjectMembers.query.filter_by(project_id=project.id).all()
    member_users = [User.query.get(m.user_id) for m in members if User.query.get(m.user_id)]
    d['members'] = [user_dict(u) for u in member_users]
    d['member_count'] = len(member_users)
    issues = Issue.query.filter_by(project_id=project.id).all()
    d['total_issues'] = len(issues)
    d['done_issues'] = sum(1 for i in issues if i.status == 'done')
    return d


def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    issue_ids = [i.id for i in Issue.query.filter_by(project_id=project.id).all()]
    if issue_ids:
        Notification.query.filter(db.or_(
            Notification.project_id == project.id,
            Notification.issue_id.in_(issue_ids),
        )).delete(synchronize_session='fetch')
        Comment.query.filter(Comment.issue_id.in_(issue_ids)).delete(synchronize_session='fetch')
        IssueAssignees.query.filter(IssueAssignees.issue_id.in_(issue_ids)).delete(synchronize_session='fetch')
        Issue.query.filter(Issue.id.in_(issue_ids)).delete(synchronize_session='fetch')
    else:
        Notification.query.filter_by(project_id=project.id).delete(synchronize_session='fetch')
    Sprint.query.filter_by(project_id=project.id).delete()
    ProjectMembers.query.filter_by(project_id=project.id).delete()
    db.session.delete(project)
    db.session.commit()
    return {'ok': True}


def project_members(project_id):
    project = Project.query.get_or_404(project_id)
    members = ProjectMembers.query.filter_by(project_id=project.id).all()
    result = []
    for m in members:
        user = User.query.get(m.user_id)
        if user:
            d = user_dict(user)
            d['joined_at'] = m.joined_at.isoformat() if hasattr(m, 'joined_at') and m.joined_at else None
            result.append(d)
    return result


def add_member(project_id, user_id):
    project = Project.query.get_or_404(project_id)
    if not user_id:
        return {'ok': False, 'error': 'user_id is required.'}, 400
    user = User.query.get(int(user_id))
    if not user:
        return {'ok': False, 'error': 'User not found.'}, 404
    existing = ProjectMembers.query.filter_by(project_id=project.id, user_id=user.id).first()
    if existing:
        return {'ok': False, 'error': 'User is already a member.'}, 409
    db.session.add(ProjectMembers(project_id=project.id, user_id=user.id))
    db.session.commit()
    return {'ok': True, 'member': user_dict(user)}, 201


def remove_member(project_id, user_id):
    ProjectMembers.query.filter_by(project_id=project_id, user_id=user_id).delete()
    db.session.commit()
    return {'ok': True}


def create_project(data, actor):
    name = (data.get('name') or '').strip()
    if not name:
        return {'ok': False, 'error': 'Project name is required.'}, 400
    if len(name) > 160:
        return {'ok': False, 'error': 'Project name is too long.'}, 400
    start_date = data.get('start_date')
    end_date = data.get('target_date') or data.get('due_date')
    if not start_date:
        return {'ok': False, 'error': 'Start date is required.'}, 400
    if not end_date:
        return {'ok': False, 'error': 'Target date is required.'}, 400
    ok, err = validate_project_dates(start_date, end_date)
    if not ok:
        return {'ok': False, 'error': err}, 400

    manager = data.get('manager') or data.get('manager_id')
    if isinstance(manager, str):
        manager = manager.strip()
    manager_user = None
    if isinstance(manager, int) or (isinstance(manager, str) and manager.isdigit()):
        manager_user = User.query.get(int(manager))
    elif manager:
        manager_user = User.query.filter_by(initials=str(manager).upper()).first()
    if not manager_user:
        return {'ok': False, 'error': 'Assignee is required and must be a valid user.'}, 400
    if manager_user.status and manager_user.status.lower() != 'active':
        return {'ok': False, 'error': 'Assignee must be an active user.'}, 400

    assignee_ids = data.get('assignees') or data.get('team_members') or []
    if not isinstance(assignee_ids, list):
        return {'ok': False, 'error': 'Team members must be a list.'}, 400
    seen_ids = set()
    validated_users = []
    for uid in assignee_ids:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid team member ID.'}, 400
        if uid_int in seen_ids:
            return {'ok': False, 'error': 'Duplicate team member IDs are not allowed.'}, 400
        seen_ids.add(uid_int)
        user = User.query.get(uid_int)
        if not user:
            return {'ok': False, 'error': f'Team member user ID {uid_int} does not exist.'}, 400
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
    try:
        for user in validated_users:
            notification_service.create_project_added_notification(project, user, actor)
        if manager_user.id not in {u.id for u in validated_users}:
            notification_service.create_project_added_notification(project, manager_user, actor)
    except Exception:
        pass
    return project_dict(project), 201


def update_project(project_id, data, actor):
    project = Project.query.get_or_404(project_id)
    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return {'ok': False, 'error': 'Project name is required.'}, 400
        project.name = name
    if 'description' in data:
        project.description = data.get('description') or ''
    if 'priority' in data:
        project.health_scope = (data.get('priority') or '')
    start_date = data.get('start_date', project.start_date)
    end_date = data.get('target_date', data.get('due_date', project.due_date))
    ok, err = validate_project_dates(start_date, end_date)
    if not ok:
        return {'ok': False, 'error': err}, 400
    if 'start_date' in data:
        project.start_date = data['start_date']
    if 'target_date' in data or 'due_date' in data:
        project.due_date = data.get('target_date', data.get('due_date'))
    if 'status' in data:
        project.status = data['status']
    db.session.commit()
    try:
        notification_service.create_project_updated_notification(project, actor)
    except Exception:
        pass
    return project_dict(project)