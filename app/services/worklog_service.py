"""Team Work Time business logic.

Team Work Time is aggregated in ONE place: the ``working_minutes`` value
stored on each Task (Issue) row. That single value is the source of truth —
login/logout, session duration, page activity, legacy Work Logs and the
automatic timer never contribute to these totals. Every query is scoped by
``project_id`` so one user's time in another project can never leak into this
project's view.

The effective work item is always the LEAF of the task tree: a subtask counts
its own working_minutes, a top-level task counts only when it has no children,
and a parent WITH children never counts its own minutes — so a parent + its
subtasks are never double-counted. Aggregation runs in the database (grouped
SUM over issues); the summary card shows Today and Total only.

Legacy Work Log / timer endpoints below remain callable (tables stay intact
for historical data) but a Work Log can no longer influence any total.

Audit identities on legacy Work Logs:
  * worked_by_user_id — the person who actually performed the work. Must be a
    member (or lead) of THIS project.
  * logged_by_user_id — the authenticated user who entered the record, always
    derived from the session server-side (never trusted from the frontend).
"""
from datetime import datetime, timedelta
import re

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Issue, Project, ProjectMembers, User, WorkLog, WorkTimer


def _minutes_to_text(minutes):
    minutes = int(minutes or 0)
    if minutes <= 0:
        return '0h 00m'
    h, m = divmod(minutes, 60)
    return f'{h}h {m:02d}m'


def _worklog_dict(row):
    issue = row.issue
    issue_key = None
    is_subtask = False
    parent_key = None
    parent_title = None
    if issue is not None:
        issue_key = f'{issue.project.key}-{issue.number}' if issue.project else f'#{issue.id}'
        is_subtask = issue.parent_issue is not None
        if is_subtask:
            parent_key = f'{issue.parent_issue.project.key}-{issue.parent_issue.number}'
            parent_title = issue.parent_issue.title
    worked_by = row.worked_by
    logged_by = row.logged_by
    return {
        'id': row.id,
        'project_id': row.project_id,
        'issue_id': row.issue_id,
        'issue_key': issue_key,
        'is_subtask': is_subtask,
        'parent_key': parent_key,
        'parent_title': parent_title,
        'worked_by_user_id': row.worked_by_user_id,
        'worked_by_name': worked_by.name if worked_by else None,
        'worked_by_initials': worked_by.initials if worked_by else None,
        'worked_by_color': worked_by.color if worked_by else '#9ca3af',
        'logged_by_user_id': row.logged_by_user_id,
        'logged_by_name': logged_by.name if logged_by else None,
        'work_date': row.work_date.isoformat() if row.work_date else None,
        'start_time': row.start_time,
        'end_time': row.end_time,
        'duration_minutes': row.duration_minutes,
        'duration_text': _minutes_to_text(row.duration_minutes),
        'description': row.description or '',
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    }


def _sum_effective_by_user(project_id, *filters):
    """Grouped SUM(Issue.working_minutes) per assignee for effective work items.

    Effective = the LEAF of the task tree within this project: a subtask
    (parent_issue_id NOT NULL) counts its own minutes; a top-level task counts
    only when it has NO children; a parent WITH children never counts its own
    working_minutes (no parent+subtask double counting). Only Done tasks with a
    recorded working_minutes and an assignee contribute. Because each member
    group is filtered/scoped by this project, per-member sums always add up to
    the project total.
    """
    children_alias = db.aliased(Issue)
    has_children = (db.session.query(children_alias.id)
                    .filter(children_alias.parent_issue_id == Issue.id)
                    .correlate(Issue).exists())
    q = (db.session.query(Issue.assignee_id, db.func.sum(Issue.working_minutes))
         .filter(
             Issue.project_id == project_id,
             Issue.status == 'done',
             Issue.working_minutes.isnot(None),
             Issue.assignee_id.isnot(None),
             db.or_(Issue.parent_issue_id.isnot(None), ~has_children),
         ))
    for f in filters:
        if f is not None:
            q = q.filter(f)
    rows = q.group_by(Issue.assignee_id).all()
    return {user_id: int(total or 0) for user_id, total in rows}


def _project_member_ids(project_id):
    rows = ProjectMembers.query.filter_by(project_id=project_id).all()
    return [r.user_id for r in rows]


def _is_project_member(project_id, user_id):
    return (ProjectMembers.query.filter_by(project_id=project_id, user_id=user_id).first()
            is not None)


def _is_project_lead(project, user_id):
    return bool(project is not None and project.lead_id and project.lead_id == user_id)


def _member_of(project, user_id):
    """A user who may appear as worked_by / may view this project's time."""
    return _is_project_lead(project, user_id) or _is_project_member(project.id, user_id)


def _can_log_on_behalf_of(actor, project):
    """Existing project permission: the project lead or a workspace
    administrator may record (and view) work on behalf of project members.
    Reuses the application's existing permission fields — it introduces no
    separate role system."""
    if actor is None:
        return False
    if _is_project_lead(project, actor.id):
        return True
    return getattr(actor, 'permission_role', None) == 'administrator'


def _can_manage(actor, project, log):
    """Who may edit/delete a work log: the worker, the person who entered the
    log, the project lead, or a workspace administrator."""
    if actor is None:
        return False
    if log.worked_by_user_id == actor.id:
        return True
    if log.logged_by_user_id == actor.id:
        return True
    if _is_project_lead(project, actor.id):
        return True
    return getattr(actor, 'permission_role', None) == 'administrator'


def _norm_hm(value):
    """Normalize a time value to 24-hour 'HH:MM'.

    Accepts 24-hour ('10:00', '14:15') and 12-hour ('10:00 AM', '2:30 PM',
    '12:00 am') forms. Returns None for missing/empty/invalid values.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r'^(\d{1,2}):([0-5]\d)\s*([APap][Mm])?$', s)
    if not m:
        return None
    hours = int(m.group(1))
    minutes = int(m.group(2))
    suffix = (m.group(3) or '').upper()
    if suffix:
        if hours < 1 or hours > 12:
            return None
        if suffix == 'AM':
            if hours == 12:
                hours = 0
        elif hours != 12:
            hours += 12
    elif hours > 23:
        return None
    return f'{hours:02d}:{minutes:02d}'


def _resolve_time_range(data):
    """Compute (start_hm, end_hm, duration_minutes) from ``start_time`` /
    ``end_time`` — the ONLY source of truth for the length of a work log.

    Any ``duration`` / ``duration_minutes`` submitted by the frontend is
    deliberately ignored. Rejections follow a clear order so a user opening
    the modal always gets the most useful message:

        missing start / missing end / invalid time
        -> 'End time must be after start time.'  (end < start)
        -> 'Work duration must be greater than zero.'  (end == start)

    Returns (start_hm, end_hm, minutes, error) with ``error`` carrying the
    message when invalid. Overnight work is not supported: end must be on or
    after the start on the selected work date, per the application's
    single-day (UTC wall-clock) convention.
    """
    raw_start = data.get('start_time')
    raw_end = data.get('end_time')
    if raw_start is None or str(raw_start).strip() == '':
        return None, None, None, 'Start time is required.'
    if raw_end is None or str(raw_end).strip() == '':
        return None, None, None, 'End time is required.'
    start_hm = _norm_hm(raw_start)
    if start_hm is None:
        return None, None, None, 'Invalid start time. Use HH:MM (e.g. 09:30).'
    end_hm = _norm_hm(raw_end)
    if end_hm is None:
        return None, None, None, 'Invalid end time. Use HH:MM (e.g. 12:30).'

    def _hm_to_minutes(hm):
        hh, mm = hm.split(':')
        return int(hh) * 60 + int(mm)

    start_minutes = _hm_to_minutes(start_hm)
    end_minutes = _hm_to_minutes(end_hm)
    if end_minutes < start_minutes:
        return None, None, None, 'End time must be after start time.'
    if end_minutes == start_minutes:
        return None, None, None, 'Work duration must be greater than zero.'
    return start_hm, end_hm, end_minutes - start_minutes, None


def _parse_date(value):
    if not value:
        return None
    s = str(value).strip()
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def _resolve_issue(project_id, issue_id):
    """An optional issue must belong to the same project as the work log."""
    if issue_id in (None, '') or issue_id == '0':
        return None, None
    try:
        issue_id_int = int(issue_id)
    except (TypeError, ValueError):
        return None, 'Invalid issue.'
    issue = Issue.query.get(issue_id_int)
    if issue is None:
        return None, 'Issue not found.'
    if issue.project_id != project_id:
        return None, 'Issue does not belong to this project.'
    return issue, None


def _resolve_worked_by(project, actor, data):
    """Resolve who actually performed the work.

    The logged-in user is always the default. Selecting another member is only
    allowed when the existing permission system permits logging on behalf of
    others (project lead / administrator) and that user is a member (or the
    lead) of THIS project.

    Returns (user_id, error, status).
    """
    raw = data.get('worked_by_user_id')
    if raw in (None, '') or str(raw).strip() == '':
        return actor.id, None, None
    try:
        desired = int(raw)
    except (TypeError, ValueError):
        return None, 'Invalid worked_by user.', 400
    if desired != actor.id and not _can_log_on_behalf_of(actor, project):
        return None, 'You can only log work for yourself.', 403
    user = User.query.get(desired)
    if user is None:
        return None, 'Worked-by user not found.', 400
    if not _member_of(project, user.id):
        return None, f'{user.name} is not a member of this project.', 400
    return user.id, None, None


def summary(project_id, actor=None):
    """Per-member working hours for ONE project: Today / Total.

    Includes every project member (zero-hour members render 0h 00m) and a
    project-wide total for the same windows. All windows are computed from
    grouped SQL queries filtered by this project's id. Totals come from task
    Working Hours only (leaf work items of Done tasks).

    The weekly summary was intentionally removed from this card.
    """
    project = Project.query.get(project_id)
    if project is None:
        return {'ok': False, 'error': 'Project not found.'}, 404
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You are not a member of this project.'}, 403

    today = datetime.utcnow().date()

    today_minutes = _sum_effective_by_user(
        project_id, db.func.date(Issue.completed_at) == today)
    total_minutes = _sum_effective_by_user(project_id)

    member_rows = (db.session.query(ProjectMembers.user_id)
                   .filter(ProjectMembers.project_id == project.id).all())
    member_ids = {r.user_id for r in member_rows}
    if project.lead_id:
        member_ids.add(project.lead_id)
    member_ids = sorted(member_ids)

    members = []
    for uid in member_ids:
        user = User.query.get(uid)
        if user is None:
            continue
        members.append({
            'user_id': user.id,
            'name': user.name,
            'initials': user.initials,
            'color': user.color,
            'role': user.role,
            'is_lead': user.id == project.lead_id,
            'today_minutes': today_minutes.get(user.id, 0),
            'total_minutes': total_minutes.get(user.id, 0),
            'today_text': _minutes_to_text(today_minutes.get(user.id, 0)),
            'total_text': _minutes_to_text(total_minutes.get(user.id, 0)),
        })
    members.sort(key=lambda m: (m['name'] or '').lower())

    project_totals = {
        'today_minutes': sum(today_minutes.values()),
        'total_minutes': sum(total_minutes.values()),
        'today_text': _minutes_to_text(sum(today_minutes.values())),
        'total_text': _minutes_to_text(sum(total_minutes.values())),
    }

    return {
        'ok': True,
        'project_id': project.id,
        'project_key': project.key,
        'today': today.isoformat(),
        'current_user_id': actor.id,
        'can_log_for_others': _can_log_on_behalf_of(actor, project),
        'members': members,
        'totals': project_totals,
    }, 200


def list_worklogs(project_id, user_id=None, work_date=None, actor=None):
    """The raw entries behind a total, always scoped to one project.

    A normal member may list only their own entries. A project lead /
    administrator may list any member's entries of this project.
    """
    project = Project.query.get(project_id)
    if project is None:
        return {'ok': False, 'error': 'Project not found.'}, 404
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You are not a member of this project.'}, 403

    q = WorkLog.query.filter_by(project_id=project.id)
    scope_user = None
    if user_id:
        try:
            scope_user = int(user_id)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Invalid user.'}, 400
        if scope_user != actor.id and not _can_log_on_behalf_of(actor, project):
            return {'ok': False, 'error': 'You can only view your own work logs.'}, 403
        q = q.filter(WorkLog.worked_by_user_id == scope_user)
    elif not _can_log_on_behalf_of(actor, project):
        q = q.filter(WorkLog.worked_by_user_id == actor.id)
    if work_date:
        d = _parse_date(work_date)
        if d is None:
            return {'ok': False, 'error': 'Invalid work date.'}, 400
        q = q.filter(WorkLog.work_date == d)
    rows = q.order_by(WorkLog.work_date.desc(), WorkLog.id.desc()).all()
    return {'ok': True, 'project_id': project.id,
            'work_logs': [_worklog_dict(r) for r in rows]}, 200


def create_worklog(data, actor):
    project = None
    if data.get('project_id'):
        try:
            project = Project.query.get(int(data['project_id']))
        except (TypeError, ValueError):
            project = None
    if project is None:
        return {'ok': False, 'error': 'Project not found.'}, 404
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You must be a member of this project to log work.'}, 403

    work_date = _parse_date(data.get('work_date'))
    if work_date is None:
        return {'ok': False, 'error': 'A valid work date is required.'}, 400

    start_hm, end_hm, duration_minutes, err = _resolve_time_range(data)
    if err:
        return {'ok': False, 'error': err}, 400

    issue, err = _resolve_issue(project.id, data.get('issue_id'))
    if err:
        return {'ok': False, 'error': err}, 400

    worked_by_user_id, err, err_status = _resolve_worked_by(project, actor, data)
    if err:
        return {'ok': False, 'error': err}, err_status or 400

    description = str(data.get('description') or '').strip()
    if len(description) > 1000:
        return {'ok': False, 'error': 'Description must be 1000 characters or fewer.'}, 400

    log = WorkLog(
        project_id=project.id,
        issue_id=issue.id if issue else None,
        worked_by_user_id=worked_by_user_id,
        logged_by_user_id=actor.id,
        work_date=work_date,
        start_time=start_hm,
        end_time=end_hm,
        duration_minutes=duration_minutes,
        description=description,
    )
    db.session.add(log)
    db.session.commit()
    return {'ok': True, 'work_log': _worklog_dict(log)}, 201


def update_worklog(log_id, data, actor):
    log = WorkLog.query.get(log_id)
    if log is None:
        return {'ok': False, 'error': 'Work log not found.'}, 404
    project = Project.query.get(log.project_id)
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You are not a member of this project.'}, 403
    if not _can_manage(actor, project, log):
        return {'ok': False, 'error': 'You can only edit your own work logs.'}, 403

    if 'work_date' in data and data.get('work_date'):
        work_date = _parse_date(data['work_date'])
        if work_date is None:
            return {'ok': False, 'error': 'A valid work date is required.'}, 400
        log.work_date = work_date

    if 'start_time' in data or 'end_time' in data:
        start_hm, end_hm, duration_minutes, err = _resolve_time_range(data)
        if err:
            return {'ok': False, 'error': err}, 400
        log.start_time = start_hm
        log.end_time = end_hm
        log.duration_minutes = duration_minutes

    if 'issue_id' in data:
        issue, err = _resolve_issue(project.id, data.get('issue_id'))
        if err:
            return {'ok': False, 'error': err}, 400
        log.issue_id = issue.id if issue else None

    if 'worked_by_user_id' in data:
        worked_by_user_id, err, err_status = _resolve_worked_by(project, actor, data)
        if err:
            return {'ok': False, 'error': err}, err_status or 400
        log.worked_by_user_id = worked_by_user_id

    if 'description' in data:
        description = str(data.get('description') or '').strip()
        if len(description) > 1000:
            return {'ok': False, 'error': 'Description must be 1000 characters or fewer.'}, 400
        log.description = description

    db.session.commit()
    return {'ok': True, 'work_log': _worklog_dict(log)}, 200


def delete_worklog(log_id, actor):
    log = WorkLog.query.get(log_id)
    if log is None:
        return {'ok': False, 'error': 'Work log not found.'}, 404
    project = Project.query.get(log.project_id)
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You are not a member of this project.'}, 403
    if not _can_manage(actor, project, log):
        return {'ok': False, 'error': 'You can only delete your own work logs.'}, 403
    db.session.delete(log)
    db.session.commit()
    return {'ok': True}, 200


# ============================================================================
# Automatic work timer (Start Work / Stop Work)
# ============================================================================
#
# Production rules:
#   * The backend generates started_at / stopped_at (server/database time).
#     The browser clock is ONLY used to draw the live counter and is never
#     authoritative; the final duration is computed from persisted timestamps.
#   * One active timer per user — enforced by the partial unique index
#     `uq_work_timer_one_active` (user_id WHERE stopped_at IS NULL), so two
#     race-y Start requests cannot both succeed.
#   * Stop is transactional and idempotent-safe: the active row is locked,
#     a WorkLog is created (SAME table as manual Log Work), the timer is
#     closed with stopped_at + work_log_id, and everything commits together.
#     A duplicate Stop finds no ACTIVE timer and returns 409 with no log.
#   * user_id is always the authenticated user — there is no way to start a
#     timer on behalf of another member (no forged worked_by).
#   * An active timer is NEVER counted toward Team Work Time; only the Work
#     Log created at Stop contributes (Today / Total / Project Total).
#   * Reassigning the issue later does not move the timer or the resulting log.

def _issue_key(issue):
    if issue is None:
        return None
    if issue.project is not None:
        return f'{issue.project.key}-{issue.number}'
    return f'#{issue.id}'


def _timer_dict(timer, server_now=None):
    """Serialize a WorkTimer row for the API.

    ``started_at`` / ``server_now`` are emitted as UTC instants (explicit Z
    suffix) so the frontend converts them with :func:`Date.parse` as UTC and
    derives the elapsed display from time deltas — never by counting ticks.
    """
    now = server_now or datetime.utcnow()
    is_active = timer.stopped_at is None
    elapsed_seconds = None
    if is_active:
        elapsed_seconds = max(0, int((now - timer.started_at).total_seconds()))
    return {
        'id': timer.id,
        'user_id': timer.user_id,
        'project_id': timer.project_id,
        'project_key': timer.project.key if timer.project else None,
        'issue_id': timer.issue_id,
        'issue_key': _issue_key(timer.issue),
        'issue_title': timer.issue.title if timer.issue else None,
        'started_at': timer.started_at.isoformat() + 'Z',
        'server_now': now.isoformat() + 'Z',
        'elapsed_minutes': (
            None if not is_active else max(0, int((now - timer.started_at).total_seconds() // 60))),
        'elapsed_seconds': elapsed_seconds,
        'stopped_at': timer.stopped_at.isoformat() + 'Z' if timer.stopped_at else None,
        'work_log_id': timer.work_log_id,
    }


def _get_active_timer(user_id, project_id=None, for_update=False):
    q = WorkTimer.query.filter_by(user_id=user_id, stopped_at=None)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    if for_update:
        q = q.with_for_update()
    return q.first()


def timer_active(actor, project_id=None):
    """The authenticated user's active timer (if any).

    Usable by any page to keep the live counter running across refresh and
    navigation. Returns active=false when there is no running timer.
    """
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401
    timer = _get_active_timer(actor.id, project_id=project_id)
    if timer is None:
        return {'ok': True, 'active': False, 'timer': None}, 200
    return {'ok': True, 'active': True, 'timer': _timer_dict(timer)}, 200


def timer_start(data, actor):
    """Start a work session on an issue (server-side timestamp).

    Validates project access, issue ownership and the one-active-timer rule.
    """
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401

    try:
        project_id = int(data.get('project_id'))
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'A valid project is required.'}, 400
    project = Project.query.get(project_id)
    if project is None:
        return {'ok': False, 'error': 'Project not found.'}, 404
    if not _member_of(project, actor.id):
        return {'ok': False, 'error': 'You are not a member of this project.'}, 403

    issue_id = data.get('issue_id')
    if issue_id in (None, '') or issue_id == '0':
        return {'ok': False, 'error': 'An issue is required to start work on.'}, 400
    try:
        issue_id = int(issue_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'Invalid issue.'}, 400
    issue = Issue.query.get(issue_id)
    if issue is None:
        return {'ok': False, 'error': 'Issue not found.'}, 404
    if issue.project_id != project.id:
        return {'ok': False, 'error': 'Issue does not belong to this project.'}, 400

    existing = _get_active_timer(actor.id)
    if existing is not None:
        return ({'ok': False,
                 'error': f'You already have an active work timer for '
                          f'{_issue_key(existing.issue)}. Stop it before starting another task.'},
                409)

    timer = WorkTimer(user_id=actor.id, project_id=project.id, issue_id=issue.id,
                      started_at=datetime.utcnow())
    db.session.add(timer)
    try:
        db.session.commit()
    except IntegrityError:
        # Concurrent Start: the partial unique index rejected the second row.
        db.session.rollback()
        other = _get_active_timer(actor.id)
        if other is not None:
            return ({'ok': False,
                     'error': f'You already have an active work timer for '
                              f'{_issue_key(other.issue)}. Stop it before starting another task.'},
                    409)
        return {'ok': False, 'error': 'Could not start work. Try again.'}, 500
    return {'ok': True, 'timer': _timer_dict(timer)}, 201


def timer_stop(data, actor):
    """Stop the active timer and finalize a Work Log (server-side timestamp).

    The active row is locked with SELECT ... FOR UPDATE so a concurrent Stop
    cannot double-finalize: after the first commit, the second sees the row is
    no longer active and returns 409 without creating a second Work Log.
    """
    if actor is None:
        return {'ok': False, 'error': 'Authentication required.'}, 401

    timer = _get_active_timer(actor.id, for_update=True)
    if timer is None:
        return {'ok': False, 'error': 'No active work timer to stop.'}, 409

    requested_issue = data.get('issue_id')
    if requested_issue not in (None, '') and str(requested_issue) != '0':
        try:
            requested_issue = int(requested_issue)
        except (TypeError, ValueError):
            requested_issue = None
        if requested_issue is not None and requested_issue != timer.issue_id:
            return ({'ok': False,
                     'error': f'You have an active work timer for '
                              f'{_issue_key(timer.issue)}. Stop that one first.'},
                    409)

    now = datetime.utcnow()
    seconds = (now - timer.started_at).total_seconds()
    if seconds <= 0:
        # Zero/negative duration is rejected; the timer stays active so the
        # user can Start again and Stop after working.
        return {'ok': False, 'error': 'Work duration must be greater than zero.'}, 409

    duration_minutes = max(1, int(round(seconds / 60)))
    work_date = timer.started_at.date()
    # Wall-clock representation on the START day (application's single-day UTC
    # convention, same as manual Log Work). Overnight sessions are represented
    # as the full tracked amount on the day the work started.
    start_hm = timer.started_at.strftime('%H:%M')
    end_hm = (timer.started_at + timedelta(minutes=duration_minutes)).strftime('%H:%M')

    log = WorkLog(
        project_id=timer.project_id,
        issue_id=timer.issue_id,
        worked_by_user_id=timer.user_id,
        logged_by_user_id=actor.id,
        work_date=work_date,
        start_time=start_hm,
        end_time=end_hm,
        duration_minutes=duration_minutes,
        description='',
    )
    db.session.add(log)
    timer.stopped_at = now
    timer.work_log = log
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return {'ok': False, 'error': 'Unable to stop work. Try again.'}, 500

    return {'ok': True,
            'work_log': _worklog_dict(log),
            'timer': _timer_dict(timer, server_now=now)}, 201