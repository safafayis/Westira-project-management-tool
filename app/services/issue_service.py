"""Issue + comment business logic."""
import re
from datetime import datetime

from app.extensions import db
from app.models import (Activity, Comment, Issue, IssueAssignees, Notification,
                        Project, ProjectMembers, Sprint, User, WorkLog)
from app.services import notification_service
from app.utils.helpers import (
    ISSUE_TYPE_COLORS,
    KANBAN_STATUSES,
    PRIORITY_COLORS,
    STATUS_LABELS,
    issue_dict,
    issue_ref,
)
from app.utils.validators import validate_task_dates


# ------------------------------------------------------------------
# Project access (same convention as the work log service: an anonymous
# actor is rejected with 401 and a non-member with 403; a project lead or a
# workspace administrator always passes)
# ------------------------------------------------------------------
def _is_project_lead(project, user_id):
    return bool(project is not None and project.lead_id and project.lead_id == user_id)


def _is_project_member(project, user_id):
    if project is None:
        return False
    return ProjectMembers.query.filter_by(project_id=project.id, user_id=user_id).first() is not None


def _can_access_project(project, actor):
    """Issue mutations are scoped to project membership.

    Cross-project and anonymous writes are rejected so one project's tasks can
    never be changed by someone outside it (rule: no unauthorized writes).
    """
    if actor is None:
        return 'Authentication required.', 401
    if not (_is_project_lead(project, actor.id) or _is_project_member(project, actor.id)):
        return 'You are not a member of this project.', 403
    return None, None


def _resolve_parent_any(value, own_issue_id=None):
    """Resolve and validate a parent task WITHOUT a project constraint.

    Used when the parent itself determines the project (subtask creation):
    the caller derives ``project.parent`` and verifies any frontend-supplied
    project against it afterwards.

    Rules enforced (single Subtask level):
      * parent optional — None/blank means "no parent"
      * parent must exist
      * parent must itself be a top-level task (no subtask-of-subtask)
      * an issue cannot be its own parent

    Returns the parent Issue (or None) on success, or an
    ``({'ok': False, 'error': msg}, status)`` tuple to short-circuit.
    """
    if value in (None, '', 0, '0'):
        return None
    try:
        parent_id = int(value)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'Invalid parent task.'}, 400
    if own_issue_id is not None and parent_id == own_issue_id:
        return {'ok': False, 'error': 'A task cannot be its own parent.'}, 400
    parent = Issue.query.get(parent_id)
    if parent is None:
        return {'ok': False, 'error': 'Parent task not found.'}, 400
    if parent.parent_issue_id is not None:
        return {'ok': False, 'error': 'A subtask cannot have its own subtask.'}, 400
    return parent


def _resolve_parent(value, project_id, own_issue_id=None):
    """``_resolve_parent_any`` plus the same-project rule (used on updates)."""
    parent = _resolve_parent_any(value, own_issue_id)
    if isinstance(parent, tuple) or parent is None:
        return parent
    if parent.project_id != project_id:
        return {'ok': False, 'error': 'Parent task must belong to the same project.'}, 400
    return parent


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
    if args.get('top_level') in ('1', 'true', 'True'):
        q = q.filter(Issue.parent_issue_id.is_(None))
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

    # Subtask rule: the parent defines the project. A subtask may only live in
    # the parent's project, so the project is DERIVED from the parent task and
    # a frontend-supplied project key is only trusted when it MATCHES it.
    parent_issue = _resolve_parent_any(data.get('parent_issue_id') or data.get('parent_id'),
                                       own_issue_id=None)
    if isinstance(parent_issue, tuple):
        return parent_issue

    if parent_issue is not None:
        project = parent_issue.project
        if project is None:
            return {'ok': False, 'error': 'Invalid project.'}, 400
        supplied = (data.get('project') or '').strip().upper()
        if supplied and supplied != project.key:
            return {'ok': False,
                    'error': 'Parent task must belong to the same project.'}, 400
    else:
        project = Project.query.filter_by(key=(data.get('project') or 'ECOM').upper()).first()
        if not project:
            return {'ok': False, 'error': 'Invalid project.'}, 400

    err, status = _can_access_project(project, actor)
    if err:
        return {'ok': False, 'error': err}, status

    subtask_order = 0
    if parent_issue is not None:
        max_order = (db.session.query(db.func.max(Issue.subtask_order))
                     .filter(Issue.parent_issue_id == parent_issue.id).scalar() or 0)
        subtask_order = (max_order or 0) + 1

    issue_type = data.get('issue_type') or 'Story'
    if issue_type not in ISSUE_TYPE_COLORS:
        return {'ok': False, 'error': 'Invalid issue type.'}, 400

    priority = data.get('priority') or 'Medium'
    if priority not in PRIORITY_COLORS:
        return {'ok': False, 'error': 'Invalid priority.'}, 400

    status = str(data.get('status') or 'backlog').strip().lower()
    if status not in KANBAN_STATUSES:
        return {'ok': False, 'error': 'Invalid status.'}, 400

    working_minutes = None
    if 'working_minutes' in data:
        working_minutes, wm_err = _parse_working_minutes(data.get('working_minutes'))
        if wm_err:
            return {'ok': False, 'error': wm_err}, 400
        if status != 'done':
            if working_minutes is not None:
                return {'ok': False,
                        'error': 'Working hours can only be recorded when the task is marked Done.'}, 400
        elif working_minutes is not None and working_minutes <= 0:
            return {'ok': False, 'error': 'Working hours must be greater than zero.'}, 400

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

    # Assignee rule: a task may only be assigned to members of its project
    # (a project lead always qualifies). Cross-project assignees are rejected:
    # no "Project A task + Project B user".
    for u in all_assignee_users:
        if not (_is_project_lead(project, u.id) or _is_project_member(project, u.id)):
            return {'ok': False,
                    'error': f'{u.name} ({u.initials}) is not a member of project {project.key}.'}, 400

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
    # Sprint rule: the parent task's Sprint is authoritative. A subtask is
    # born in the same sprint container as its parent (inherited server-side,
    # never taken from the frontend). For a top-level task the sprint comes
    # from the form when supplied.
    sprint = None
    if parent_issue is not None:
        if parent_issue.sprint_id:
            sprint = Sprint.query.filter_by(id=parent_issue.sprint_id,
                                            project_id=project.id).first()
        if data.get('sprint') and sprint is not None:
            supplied_number = data['sprint']
            if str(supplied_number).strip() != str(sprint.number):
                return {'ok': False,
                        'error': 'A subtask inherits the sprint from its parent task.'}, 400
    elif data.get('sprint'):
        try:
            sprint = Sprint.query.filter_by(number=int(data['sprint']),
                                            project_id=project.id).first()
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid sprint.'}, 400
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
        parent_issue_id=parent_issue.id if parent_issue else None,
        subtask_order=subtask_order,
        working_minutes=working_minutes,
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


def _truthy(v):
    return v in (True, 1, '1', 'true', 'True', 'yes', 'on')


_WORKING_HM_RE = re.compile(r'^\s*(\d{1,3})\s*:\s*([0-5]?\d)\s*$')


def _parse_working_minutes(value):
    """Parse task Working Hours into integer minutes.

    Accepts an integer (raw minutes), a string of digits (minutes), or an
    'HH:MM' / 'H:MM' duration. Empty/missing values mean "not recorded"
    (None). Returns (minutes, error).
    """
    if value is None:
        return None, None
    if isinstance(value, str) and value.strip() == '':
        return None, None
    if isinstance(value, bool):
        return None, 'Invalid working hours. Use HH:MM format (e.g. 01:30).'
    if isinstance(value, (int, float)):
        return int(value), None
    s = str(value).strip()
    m = _WORKING_HM_RE.match(s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)), None
    if s.isdigit():
        return int(s), None
    return None, 'Invalid working hours. Use HH:MM format (e.g. 01:30).'


def _apply_working_minutes(issue, data):
    """Validate and store the task's Working Hours against its target status.

    Rules (single source of truth lives on the Issue row):
      * Working hours may only be recorded when the task is Done.
      * A Done task's hours must be a positive integer minute count.
      * Reopening a Done task (done -> anything else) clears its hours.
    Returns an error tuple to short-circuit, or None when accepted.
    """
    if 'working_minutes' in data:
        minutes, err = _parse_working_minutes(data.get('working_minutes'))
        if err:
            return {'ok': False, 'error': err}, 400
        target = data.get('status', issue.status)
        if target != 'done':
            if minutes is not None:
                return {'ok': False,
                        'error': 'Working hours can only be recorded when the task is marked Done.'}, 400
        elif minutes is not None and minutes <= 0:
            return {'ok': False, 'error': 'Working hours must be greater than zero.'}, 400
        issue.working_minutes = minutes
    elif 'status' in data and data['status'] != 'done' \
            and str(issue.status or '').strip().lower() == 'done':
        # Reopening a completed task clears its recorded working hours.
        issue.working_minutes = None
    return None


def _parent_done_guard(issue, data):
    """Warn before a top-level task can be set to 'done' while any of its
    subtasks is still incomplete.

    Subtasks never change a parent's status: the parent task is only ever moved
    to done when the user confirms (re-submits with ``confirm_incomplete=true``).
    Returns an error tuple to short-circuit, or None when the move is allowed.
    """
    if issue.parent_issue_id is not None:
        return None
    if (data.get('status') or '').strip().lower() != 'done':
        return None
    if str(issue.status or '').strip().lower() == 'done':
        return None
    if _truthy(data.get('confirm_incomplete')):
        return None
    incomplete = (Issue.query
                  .filter(Issue.parent_issue_id == issue.id,
                          Issue.status != 'done')
                  .count())
    if incomplete:
        return {'ok': False,
                'error': f'This task has {incomplete} incomplete subtask(s). '
                         f'Mark the task as done anyway?',
                'needs_confirmation': True,
                'incomplete_subtasks': incomplete,
                'requires_confirm_incomplete': True}, 400
    return None


def _normalize_subtask_orders(parent_id):
    """Renumber a parent's subtasks 1..N in their current display order so no
    gaps or duplicates survive a delete/reorder."""
    children = (Issue.query.filter_by(parent_issue_id=parent_id)
                .order_by(Issue.subtask_order, Issue.position, Issue.id).all())
    for i, c in enumerate(children, start=1):
        if c.subtask_order != i:
            c.subtask_order = i


# ------------------------------------------------------------------
# Update / move / delete
# ------------------------------------------------------------------
def _record_status_activity(issue, actor, old_status):
    """Create the dashboard activity for a real status change.

    Uses the existing Activity model/table. The row is added to the current
    session so it commits atomically together with the issue status update.

    old_status must be captured *before* the status is applied so the event
    only fires when the status actually changed.
    """
    if old_status == issue.status:
        return
    actor_name = actor.name if actor is not None else 'Someone'
    label = STATUS_LABELS.get(issue.status, (issue.status or '').title())
    db.session.add(Activity(
        icon='arrow',
        color='#d97706',
        text=f'{actor_name} moved {issue_ref(issue)} to {label}',
        detail=issue.title[:240],
        time=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
    ))


def update_issue(issue_id, data, actor):
    issue = Issue.query.get_or_404(issue_id)
    err, status = _can_access_project(issue.project, actor)
    if err:
        return {'ok': False, 'error': err}, status
    guard = _parent_done_guard(issue, data)
    if guard is not None:
        return guard
    old_assignee_id = issue.assignee_id
    old_priority = issue.priority
    old_status = issue.status
    old_due_date = issue.due_date
    old_parent_id = issue.parent_issue_id
    # Validate/apply Working Hours against the TARGET status BEFORE the status
    # is mutated, so a reopen (done -> non-done) can still see it was Done.
    wm_guard = _apply_working_minutes(issue, data)
    if wm_guard is not None:
        return wm_guard
    if 'parent_issue_id' in data or 'parent_id' in data:
        parent = _resolve_parent(data.get('parent_issue_id', data.get('parent_id')),
                                 issue.project_id, own_issue_id=issue.id)
        if isinstance(parent, tuple):
            return parent
        issue.parent_issue_id = parent.id if parent else None
        if issue.parent_issue_id is not None and issue.parent_issue_id != old_parent_id:
            max_order = (db.session.query(db.func.max(Issue.subtask_order))
                         .filter(Issue.parent_issue_id == issue.parent_issue_id).scalar() or 0)
            issue.subtask_order = (max_order or 0) + 1
        elif issue.parent_issue_id is None and old_parent_id is not None:
            issue.subtask_order = 0
            _normalize_subtask_orders(old_parent_id)
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
    if 'status' in data and issue.status != old_status:
        _record_status_activity(issue, actor, old_status)
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
    err, status = _can_access_project(issue.project, actor)
    if err:
        return {'ok': False, 'error': err}, status
    guard = _parent_done_guard(issue, data)
    if guard is not None:
        return guard
    old_status = issue.status
    if 'status' in data:
        issue.status = data['status']
        if data['status'] == 'done' and old_status != 'done':
            issue.completed_at = datetime.utcnow()
        elif old_status == 'done' and data['status'] != 'done':
            issue.completed_at = None
            issue.working_minutes = None
    if 'position' in data or 'sprint' in data:
        issue.position = int(data.get('position', issue.position))
        if 'sprint' in data and data.get('sprint'):
            sp = Sprint.query.filter(
                Sprint.number == int(data['sprint']),
                Sprint.project_id == issue.project_id,
            ).first()
            issue.sprint_id = sp.id if sp else issue.sprint_id
    if 'status' in data and issue.status != old_status:
        _record_status_activity(issue, actor, old_status)
    db.session.commit()
    try:
        if 'status' in data and issue.status != old_status:
            notification_service.create_status_notification(issue, actor)
    except Exception:
        pass
    return {"ok": True, "issue": issue_dict(issue)}, 200


def _detach_and_delete(issue):
    """Delete one task row, preserving its reported historical time.

    Work logs are detached from the deleted task (they keep project + worked-by
    user, so Team Work Time totals remain accurate); comments and
    notifications tied to the task are removed.
    """
    WorkLog.query.filter_by(issue_id=issue.id).update(
        {'issue_id': None}, synchronize_session='fetch')
    Comment.query.filter_by(issue_id=issue.id).delete()
    Notification.query.filter_by(issue_id=issue.id).delete()
    db.session.delete(issue)


def delete_issue(issue_id, actor=None, data=None):
    issue = Issue.query.get_or_404(issue_id)
    err, status = _can_access_project(issue.project, actor)
    if err:
        return {'ok': False, 'error': err}, status
    subtasks = Issue.query.filter_by(parent_issue_id=issue.id).order_by(Issue.position, Issue.id).all()
    if subtasks and not (data or {}).get('confirm_subtasks'):
        return {'ok': False,
                'error': f'This task has {len(subtasks)} subtask(s). '
                         f'Delete the task and its subtasks?',
                'needs_confirmation': True,
                'subtask_count': len(subtasks)}, 400
    parent_id = issue.parent_issue_id
    for st in subtasks:
        _detach_and_delete(st)
    _detach_and_delete(issue)
    db.session.commit()
    if parent_id is not None:
        _normalize_subtask_orders(parent_id)
        db.session.commit()
    return {"ok": True}, 200


def reorder_subtask(issue_id, data, actor):
    """Persist subtask ordering.

    Accepts ``direction`` = 'up' | 'down' (swap with the adjacent sibling).
    A bare reorder with ```subtask_order`` sets the absolute 1-based position.
    Always normalizes sibling orders to 1..N afterwards.
    """
    issue = Issue.query.get_or_404(issue_id)
    err, status = _can_access_project(issue.project, actor)
    if err:
        return {'ok': False, 'error': err}, status
    if issue.parent_issue_id is None:
        return {'ok': False, 'error': 'Only subtasks can be reordered.'}, 400

    def _siblings():
        return (Issue.query.filter_by(parent_issue_id=issue.parent_issue_id)
                .order_by(Issue.subtask_order, Issue.position, Issue.id).all())

    siblings = _siblings()
    if len(siblings) < 2:
        return {'ok': True, 'issue': issue_dict(issue),
                'subtasks': [issue_dict(s) for s in siblings]}, 200

    idx = next((j for j, s in enumerate(siblings) if s.id == issue.id), None)
    if idx is None:
        return {'ok': False, 'error': 'Issue not found among its siblings.'}, 400

    direction = (data.get('direction') or '').strip().lower()
    swap_idx = None
    if direction == 'up' and idx > 0:
        swap_idx = idx - 1
    elif direction == 'down' and idx < len(siblings) - 1:
        swap_idx = idx + 1
    elif data.get('subtask_order') is not None:
        try:
            target = int(data.get('subtask_order'))
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid subtask_order.'}, 400
        swap_idx = max(0, min(len(siblings) - 1, target - 1))
        if swap_idx == idx:
            swap_idx = None

    if swap_idx is not None:
        other = siblings[swap_idx]
        issue.subtask_order, other.subtask_order = other.subtask_order, issue.subtask_order
        _normalize_subtask_orders(issue.parent_issue_id)
        db.session.commit()

    return {'ok': True, 'issue': issue_dict(issue),
            'subtasks': [issue_dict(s) for s in _siblings()]}, 200


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