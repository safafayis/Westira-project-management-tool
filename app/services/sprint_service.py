"""Sprint business logic: CRUD + lifecycle (start / complete)."""
from app.extensions import db
from app.models import Issue, Project, Sprint
from app.services import notification_service
from app.utils.helpers import (
    context_issues,
    context_project,
    context_sprints,
    format_date,
    sprint_api_dict,
)
from app.utils.validators import validate_sprint_dates


def list_sprints(project_key):
    project = context_project(project_key)
    return [sprint_api_dict(sp, context_issues(project)) for sp in context_sprints(project)]


def get_sprint(sprint_id):
    sprint = Sprint.query.get_or_404(sprint_id)
    project = Project.query.get(sprint.project_id)
    issues = context_issues(project) if project else []
    return sprint_api_dict(sprint, issues)


def create_sprint(data):
    project_key = str(data.get('project') or '').strip().upper()
    project = Project.query.filter_by(key=project_key).first()
    if not project:
        return {'ok': False, 'error': 'Project is required.',
                'field': 'project'}, 400

    name = (data.get('name') or '').strip()
    if not name:
        return {'ok': False, 'error': 'Sprint name is required.',
                'field': 'name'}, 400
    if len(name) > 80:
        return {'ok': False, 'error': 'Sprint name must be 80 characters or fewer.',
                'field': 'name'}, 400
    existing = Sprint.query.filter(Sprint.project_id == project.id,
                                   db.func.lower(Sprint.name) == name.lower()).first()
    if existing:
        return {'ok': False,
                'error': 'A sprint with this name already exists in this project.',
                'field': 'name'}, 409

    start_date = data.get('start_date')
    end_date = data.get('end_date') or data.get('target_date')
    if not start_date:
        return {'ok': False, 'error': 'Start date is required.',
                'field': 'start_date'}, 400
    if not end_date:
        return {'ok': False, 'error': 'End date is required.',
                'field': 'end_date'}, 400
    if not validate_sprint_dates(start_date, end_date):
        return {'ok': False, 'error': 'End date must be after the start date.',
                'field': 'end_date'}, 400

    requested_task_ids = data.get('task_ids') or data.get('tasks') or []
    if not isinstance(requested_task_ids, list):
        return {'ok': False, 'error': 'Tasks must be a list.',
                'field': 'tasks'}, 400
    assigned_issues = []
    seen_task_ids = set()
    for tid in requested_task_ids:
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            return {'ok': False, 'error': f'Invalid task ID {tid}.',
                    'field': 'tasks'}, 400
        if tid_int in seen_task_ids:
            continue
        seen_task_ids.add(tid_int)
        issue = Issue.query.get(tid_int)
        if not issue:
            return {'ok': False, 'error': f'Task {tid_int} does not exist.',
                    'field': 'tasks'}, 400
        if issue.project_id != project.id:
            project_label = issue.project.key if issue.project else '?'
            return {'ok': False,
                    'error': f'Task {project_label}-{issue.number} does not belong to this project.',
                    'field': 'tasks'}, 400
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
    return sprint_api_dict(sprint, context_issues(project)), 201


def update_sprint(sprint_id, data):
    sprint = Sprint.query.get_or_404(sprint_id)
    project = sprint.project

    name = (data.get('name') or '').strip()
    if not name:
        return {'ok': False, 'error': 'Sprint name is required.',
                'field': 'name'}, 400
    if len(name) > 80:
        return {'ok': False, 'error': 'Sprint name must be 80 characters or fewer.',
                'field': 'name'}, 400
    existing = Sprint.query.filter(Sprint.project_id == project.id,
                                   Sprint.id != sprint.id,
                                   db.func.lower(Sprint.name) == name.lower()).first()
    if existing:
        return {'ok': False,
                'error': 'A sprint with this name already exists in this project.',
                'field': 'name'}, 409

    start_date = data.get('start_date')
    end_date = data.get('end_date') or data.get('target_date')
    if not start_date:
        return {'ok': False, 'error': 'Start date is required.',
                'field': 'start_date'}, 400
    if not end_date:
        return {'ok': False, 'error': 'End date is required.',
                'field': 'end_date'}, 400
    if not validate_sprint_dates(start_date, end_date):
        return {'ok': False, 'error': 'End date must be after the start date.',
                'field': 'end_date'}, 400

    requested_task_ids = data.get('task_ids') or data.get('tasks') or []
    if not isinstance(requested_task_ids, list):
        return {'ok': False, 'error': 'Tasks must be a list.',
                'field': 'tasks'}, 400
    assigned_issues = []
    seen_task_ids = set()
    for tid in requested_task_ids:
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            return {'ok': False, 'error': f'Invalid task ID {tid}.',
                    'field': 'tasks'}, 400
        if tid_int in seen_task_ids:
            continue
        seen_task_ids.add(tid_int)
        issue = Issue.query.get(tid_int)
        if not issue:
            return {'ok': False, 'error': f'Task {tid_int} does not exist.',
                    'field': 'tasks'}, 400
        if issue.project_id != project.id:
            project_label = issue.project.key if issue.project else '?'
            return {'ok': False,
                    'error': f'Task {project_label}-{issue.number} does not belong to this project.',
                    'field': 'tasks'}, 400
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
    return sprint_api_dict(sprint, context_issues(project))


def start_sprint(sprint_id, actor):
    sprint = Sprint.query.get_or_404(sprint_id)
    if sprint.status == 'Completed':
        return {'ok': False, 'error': 'Completed sprints cannot be restarted.'}, 409
    if sprint.status == 'Active':
        return sprint_api_dict(sprint, context_issues(sprint.project)), 200

    active = Sprint.query.filter(Sprint.project_id == sprint.project_id,
                                 Sprint.status == 'Active',
                                 Sprint.id != sprint.id).first()
    if active:
        return {'ok': False,
                'error': 'Another sprint is already active for this project. Complete the current sprint before starting a new one.',
                'active_sprint': active.name}, 409

    sprint.status = 'Active'
    db.session.commit()
    try:
        notification_service.create_sprint_started_notification(sprint, actor)
    except Exception:
        pass
    return sprint_api_dict(sprint, context_issues(sprint.project))


def complete_sprint(sprint_id, data, actor):
    sprint = Sprint.query.get_or_404(sprint_id)
    if sprint.status == 'Completed':
        return {'ok': False, 'error': 'This sprint is already completed.'}, 409
    if sprint.status != 'Active':
        return {'ok': False, 'error': 'Sprint must be started before it can be completed.'}, 409

    project = sprint.project
    issues = [i for i in context_issues(project) if i.sprint_id == sprint.id]
    incomplete = [i for i in issues if i.status != 'done']

    incomplete_action = ((data or {}).get('incomplete_action') or '').lower()

    if incomplete and incomplete_action not in ('backlog', 'next', 'keep'):
        return {
            'ok': False,
            'error': f'{len(incomplete)} issue(s) are still incomplete in this sprint.',
            'requires_decision': True,
            'incomplete_count': len(incomplete),
            'incomplete_action': 'Choose how to handle incomplete issues before completing the sprint.',
        }, 409

    if incomplete_action == 'backlog':
        for i in incomplete:
            i.sprint_id = None
            i.status = 'backlog'
    elif incomplete_action == 'next':
        next_sprint = Sprint.query.filter(Sprint.project_id == sprint.project_id,
                                          Sprint.status != 'Completed',
                                          Sprint.id != sprint.id).order_by(Sprint.number).first()
        if not next_sprint:
            return {'ok': False, 'error': 'No next sprint is available to move incomplete issues to.',
                    'requires_decision': True}, 409
        for i in incomplete:
            i.sprint_id = next_sprint.id

    sprint.status = 'Completed'
    db.session.commit()
    try:
        notification_service.create_sprint_completed_notification(sprint, actor, incomplete=len(incomplete))
    except Exception:
        pass
    return sprint_api_dict(sprint, context_issues(project))