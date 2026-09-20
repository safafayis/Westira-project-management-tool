"""Reports & analytics business logic.

The report scope (project/sprint/assignee/status/date filters) is parsed and
validated in the API layer; every function here computes over that scope dict.

Design rules:
  * Counts, points and working-hours are computed with SQL GROUP BY
    aggregations — issue rows are never loaded into Python for a whole-report
    computation. Only overdue detection and the created_at date-range filter
    run as lightweight Python projections, because due_date / created_at are
    stored as display strings in multiple formats.
  * Working Hours follow the canonical LEAF rule (same as Team Work Time): a
    subtask counts its own minutes, a top-level task counts only when it has
    no children, and a parent WITH children never counts its own minutes.
  * ``_project_health`` (used by the project overview page) is unchanged; the
    reports page uses the separate ``_report_project_health`` rule.
"""
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import aliased as sa_aliased
from sqlalchemy.orm import joinedload as sa_joinedload

from app.extensions import db
from app.models import Issue, IssueAssignees, Project, Sprint, User
from app.utils.helpers import (
    KANBAN_STATUSES,
    PRIORITY_COLORS,
    STATUS_LABELS,
    format_date,
    minutes_text,
    parse_any_date,
)

REPORT_STATUS_ORDER = KANBAN_STATUSES
REPORT_PRIORITY_ORDER = ['Highest', 'High', 'Medium', 'Low', 'Lowest', 'Critical']
REPORT_STATUS_COLORS = {
    'backlog': '#9ca3af', 'todo': '#4f46e5', 'in_progress': '#0891b2',
    'in_review': '#7c3aed', 'done': '#059669',
}
REPORT_DONE_REASON_MSG = 'No completion timestamps recorded yet. Completed tasks will appear here as the team finishes work.'


# ------------------------------------------------------------------
# Shared scope queries
# ------------------------------------------------------------------
def _report_scoped_projects(scope):
    q = Project.query
    if scope['project_id']:
        q = q.filter(Project.id == scope['project_id'])
    return q.all()


def _report_scoped_sprints(scope):
    q = Sprint.query
    if scope['project_id']:
        q = q.filter(Sprint.project_id == scope['project_id'])
    if scope['sprint_id']:
        q = q.filter(Sprint.id == scope['sprint_id'])
    return q.all()


def _filter_issues_by_assignee(query, user_id):
    """Restrict an Issue query to issues assigned to a user (primary or linked)."""
    links = sa_aliased(IssueAssignees)
    exists = db.session.query(links.id).filter(
        links.issue_id == Issue.id,
        links.user_id == user_id,
    ).exists()
    return query.filter(db.or_(Issue.assignee_id == user_id, exists))


def _report_in_date_range(issue, scope):
    if not scope['start_date'] and not scope['end_date']:
        return True
    d = parse_any_date(issue.created_at)
    if not d:
        return False
    if scope['start_date'] and d.date() < scope['start_date']:
        return False
    if scope['end_date'] and d.date() > scope['end_date']:
        return False
    return True


def _report_scoped_issues(scope):
    """Issues matching the report scope, relationship-loaded.

    Used only by bounded drill-down lists. Whole-report computations never
    go through here — they use the SQL aggregations below.
    """
    q = Issue.query.options(
        sa_joinedload(Issue.project),
        sa_joinedload(Issue.sprint),
        sa_joinedload(Issue.assignee),
    )
    if scope['project_id']:
        q = q.filter(Issue.project_id == scope['project_id'])
    if scope['sprint_id']:
        q = q.filter(Issue.sprint_id == scope['sprint_id'])
    if scope['assignee_id']:
        q = _filter_issues_by_assignee(q, scope['assignee_id'])
    if scope['status']:
        q = q.filter(Issue.status == scope['status'])
    issues = q.all()
    if scope['start_date'] or scope['end_date']:
        issues = [i for i in issues if _report_in_date_range(i, scope)]
    return issues


def _report_issue_filters(scope, include_status=True):
    """SQL filters from the scope (everything except the date range).

    The assignee filter covers both the primary assignee and issue_assignees
    links; the date range is applied separately via ``_report_date_subset``.
    """
    flt = []
    if scope['project_id']:
        flt.append(Issue.project_id == scope['project_id'])
    if scope['sprint_id']:
        flt.append(Issue.sprint_id == scope['sprint_id'])
    if scope['assignee_id']:
        links = sa_aliased(IssueAssignees)
        exists = db.session.query(links.id).filter(
            links.issue_id == Issue.id,
            links.user_id == scope['assignee_id'],
        ).exists()
        flt.append(db.or_(Issue.assignee_id == scope['assignee_id'], exists))
    if include_status and scope['status']:
        flt.append(Issue.status == scope['status'])
    return flt


def _report_date_id_subset(scope):
    """Issue ids inside the scope's created_at date range (or None).

    ``created_at`` is stored as a display string, so this stays a lightweight
    Python projection over (id, created_at) only. Returns None when no range
    is set (meaning "no restriction").
    """
    if not scope['start_date'] and not scope['end_date']:
        return None
    flt = _report_issue_filters(scope)
    rows = (db.session.query(Issue.id, Issue.created_at).filter(*flt).all())
    subset = set()
    for iid, created in rows:
        d = parse_any_date(created)
        if not d:
            continue
        if scope['start_date'] and d.date() < scope['start_date']:
            continue
        if scope['end_date'] and d.date() > scope['end_date']:
            continue
        subset.add(iid)
    return subset


def _report_date_subset_filter(scope):
    """Additional filters restricting an aggregate query to the date subset."""
    subset = _report_date_id_subset(scope)
    return [Issue.id.in_(subset)] if subset is not None else []


def _has_children_expr():
    """Correlated EXISTS helper for the leaf work-item rule."""
    child = db.aliased(Issue)
    return (db.session.query(child.id)
            .filter(child.parent_issue_id == Issue.id)
            .correlate(Issue).exists())


def _scoped_issue_counts(scope):
    """{status: count} for scoped issues, single GROUP BY query."""
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    rows = (db.session.query(Issue.status, func.count(Issue.id))
            .filter(*flt).group_by(Issue.status).all())
    counts = {st: 0 for st in KANBAN_STATUSES}
    for st, n in rows:
        if st in counts:
            counts[st] = n
    return counts


def _sprint_aggregate(scope):
    """Per-sprint task + story-point stats for scoped issues.

    Respects the scope's status filter for consistency with the page-wide
    scope (a status-limited report drills the same numbers everywhere).
    Returns {sprint_id: {total, done, in_progress, committed, completed}}.
    """
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    rows = (db.session.query(
                Issue.sprint_id,
                func.count(Issue.id),
                func.coalesce(func.sum(case((Issue.status == 'done', 1), else_=0)), 0),
                func.coalesce(func.sum(case((Issue.status == 'in_progress', 1), else_=0)), 0),
                func.coalesce(func.sum(Issue.points), 0),
                func.coalesce(func.sum(case((Issue.status == 'done', Issue.points), else_=0)), 0),
            ).filter(*flt).group_by(Issue.sprint_id).all())
    out = {}
    for sid, total, done, in_progress, committed, completed in rows:
        out[sid or 0] = {
            'total': total,
            'done': int(done or 0),
            'in_progress': int(in_progress or 0),
            'committed': int(committed or 0),
            'completed': int(completed or 0),
        }
    return out


def _effective_minutes_query(scope, group_col=None):
    """Grouped SUM(Issue.working_minutes) over the effective (leaf) work items.

    Effective = Done tasks with recorded minutes that are either a subtask or
    a top-level task with NO children. Scoped to the report filters.
    """
    hc = _has_children_expr()
    flt = ([Issue.status == 'done',
            Issue.working_minutes.isnot(None),
            db.or_(Issue.parent_issue_id.isnot(None), ~hc)]
           + _report_issue_filters(scope, include_status=False)
           + _report_date_subset_filter(scope))
    cols = []
    if group_col is not None:
        cols.append(group_col)
    cols.append(func.coalesce(func.sum(Issue.working_minutes), 0))
    q = db.session.query(*cols).filter(*flt)
    if group_col is not None:
        q = q.group_by(group_col)
    return q


def _working_minutes_total(scope):
    return int(_effective_minutes_query(scope).scalar() or 0)


def _working_minutes_by_project(scope):
    rows = _effective_minutes_query(scope, Issue.project_id).all()
    return {pid: int(total or 0) for pid, total in rows}


def _working_minutes_by_sprint(scope):
    rows = _effective_minutes_query(scope, Issue.sprint_id).all()
    return {sid or 0: int(total or 0) for sid, total in rows}


def _working_minutes_by_assignee(scope):
    rows = _effective_minutes_query(scope, Issue.assignee_id).all()
    return {uid: int(total or 0) for uid, total in rows}


def _overdue_snapshot(scope):
    """(overdue issue ids, {project_id: overdue count}).

    A lightweight projection (id, project_id, status, due_date) because
    due_date is a display string; the date-range filter is already applied.
    """
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    rows = (db.session.query(Issue.id, Issue.project_id, Issue.status, Issue.due_date)
            .filter(*flt).all())
    today = datetime.utcnow().date()
    ids = set()
    by_project = {}
    for iid, pid, status, due in rows:
        if status == 'done':
            continue
        d = parse_any_date(due)
        if d and d.date() < today:
            ids.add(iid)
            by_project[pid] = by_project.get(pid, 0) + 1
    return ids, by_project


def _team_open_counts(scope):
    """(open assignments count, primary-assignee id set).

    Open = issues not done with a primary assignee (or legacy initials).
    Members = users who are the primary assignee of any scoped issue.
    """
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    open_rows = (db.session.query(
                    Issue.assignee_id, func.count(Issue.id))
                 .filter(*flt, Issue.status != 'done',
                         db.or_(Issue.assignee_id.isnot(None),
                                db.and_(Issue.assignee_initials.isnot(None),
                                        Issue.assignee_initials != '')))
                 .group_by(Issue.assignee_id).all())
    open_total = sum(n for _, n in open_rows)
    member_rows = (db.session.query(Issue.assignee_id)
                   .filter(*flt, Issue.assignee_id.isnot(None))
                   .group_by(Issue.assignee_id).all())
    member_ids = {uid for (uid,) in member_rows}
    return open_total, member_ids


def _days_between(start, end):
    s = parse_any_date(start)
    e = parse_any_date(end)
    if s is None or e is None:
        return None
    return max((e.date() - s.date()).days, 0)


def _report_overdue_issues(issues):
    """Overdue Issue rows (drill-down only; Python projected from due_date)."""
    today = datetime.utcnow().date()
    overdue = []
    for issue in issues:
        if issue.status == 'done':
            continue
        due = parse_any_date(issue.due_date)
        if due and due.date() < today:
            overdue.append(issue)
    overdue.sort(key=lambda i: (parse_any_date(i.due_date) or datetime.max))
    return overdue


def _report_task_dict(i):
    project = i.project
    project_key = project.key if project else 'PRJ'
    assignee = i.assignee
    return {
        'id': i.id,
        'key': f'{project_key}-{i.number}' if i.number else f'{project_key}-{i.id}',
        'title': (i.title or '').strip(),
        'status': i.status,
        'status_label': STATUS_LABELS.get(i.status, (i.status or '').title() or ''),
        'status_color': REPORT_STATUS_COLORS.get(i.status, '#9ca3af'),
        'priority': i.priority or '',
        'priority_color': i.priority_color or PRIORITY_COLORS.get(i.priority, '#6b7280'),
        'points': i.points or 0,
        'issue_type': i.issue_type or '',
        'due_date': format_date(i.due_date),
        'created_at': format_date(i.created_at),
        'completed_at': i.completed_at.strftime('%b %d, %Y') if i.completed_at else None,
        'assignee_id': i.assignee_id,
        'assignee': assignee.name if assignee else None,
        'assignee_initials': (assignee.initials if assignee else None) or i.assignee_initials,
        'assignee_color': (assignee.color if assignee else None) or i.assignee_color or '#9ca3af',
        'sprint_id': i.sprint_id,
        'sprint': i.sprint.name if i.sprint else None,
        'project': project_key,
        'project_name': project.name if project else '',
    }


def _report_velocity(scope, sprints=None):
    if sprints is None:
        sprints = _report_scoped_sprints(scope)
    completed_sprints = [s for s in sprints if s.status == 'Completed']
    points = _sprint_aggregate(scope)
    rows = []
    weighted = 0
    total_completed = 0
    for sprint in sorted(completed_sprints, key=lambda s: s.number):
        p = points.get(sprint.id, {'committed': 0, 'completed': 0})
        committed, completed_pts = p['committed'], p['completed']
        if committed > 0:
            weighted += 1
            total_completed += completed_pts
        rows.append({
            'id': sprint.id,
            'name': sprint.name,
            'number': sprint.number,
            'goal': sprint.goal or '',
            'committed': committed,
            'completed': completed_pts,
        })
    average = round(total_completed / weighted) if weighted else 0
    if not completed_sprints:
        message = 'No completed sprints available for velocity analysis.'
    elif not weighted:
        message = 'No committed sprint work recorded in completed sprints.'
    else:
        message = ''
    return {
        'sprints': rows,
        'count': weighted,
        'total_completed': total_completed,
        'average': average,
        'has_data': bool(completed_sprints),
        'message': message,
    }


def _project_health(project, total, completed, overdue, sprint_progress, progress):
    """Derive a project health rating from real task data.

    Healthy  -> no overdue work and sprint/deadline on track
    At Risk  -> overdue tasks exist, sprint behind, or deadline within 30 days
    Critical -> heavy overdue workload, sprint significantly behind, or deadline within 14 days
    """
    if total == 0:
        return 'Healthy'
    overdue_ratio = overdue / total
    if overdue_ratio >= 0.3:
        return 'Critical'
    if sprint_progress is not None:
        if sprint_progress < 40:
            return 'Critical'
        if sprint_progress < 75:
            return 'At Risk'
    if overdue > 0:
        return 'At Risk'
    if project.status and project.status.lower() != 'completed' and progress < 100:
        due = parse_any_date(project.due_date)
        if due:
            days_left = (due.date() - datetime.utcnow().date()).days
            if 0 <= days_left <= 14:
                return 'Critical'
            if days_left <= 30:
                return 'At Risk'
    return 'Healthy'


def _report_project_health(total, overdue_pct, progress):
    """Reports-page health rating (kept separate from the overview rule).

    Healthy  -> no overdue work and progress past the halfway mark
    Warning  -> some overdue work (>=10%) or progress still at/below 60%
    Critical -> overdue workload above 25%
    """
    if total == 0:
        return 'Healthy'
    if overdue_pct > 25:
        return 'Critical'
    if overdue_pct >= 10:
        return 'Warning'
    if progress > 60:
        return 'Healthy'
    return 'Warning'


# ------------------------------------------------------------------
# Endpoint payloads
# ------------------------------------------------------------------
def filters(scope):
    project_id = scope.get('project_id')
    sprints_q = Sprint.query
    if project_id:
        sprints_q = sprints_q.filter(Sprint.project_id == project_id)
    sprints = sprints_q.order_by(Sprint.number).all()

    return {
        'projects': [{'id': p.id, 'key': p.key, 'name': p.name, 'color': p.color}
                     for p in _report_scoped_projects(scope)],
        'sprints': [{'id': s.id, 'name': s.name, 'number': s.number, 'status': s.status}
                    for s in sprints],
        'assignees': [{'id': u.id, 'name': u.name, 'initials': u.initials, 'color': u.color}
                      for u in User.query.order_by(User.name).all()],
        'statuses': [{'key': st, 'label': STATUS_LABELS.get(st, st.title())}
                     for st in REPORT_STATUS_ORDER],
    }


def summary(scope):
    projects = _report_scoped_projects(scope)
    sprints = _report_scoped_sprints(scope)
    counts = _scoped_issue_counts(scope)

    total = sum(counts.values())
    completed_tasks = counts['done']
    in_progress_tasks = counts['in_progress']

    sprint_ids = {s.id for s in sprints}
    sprint_stats = _sprint_aggregate(scope)
    committed_points = sum(sprint_stats[sid]['committed'] for sid in sprint_stats if sid in sprint_ids)
    completed_points = sum(sprint_stats[sid]['completed'] for sid in sprint_stats if sid in sprint_ids)
    sprint_progress = round(completed_points / committed_points * 100) if committed_points else 0
    sprint_progress_text = (f'{completed_points} / {committed_points} story points'
                            if committed_points else 'No sprint work in scope')

    velocity = _report_velocity(scope, sprints)

    open_assigned, member_ids = _team_open_counts(scope)
    members_count = len(member_ids)
    team_workload = round(open_assigned / members_count, 1) if members_count else 0

    working_minutes = _working_minutes_total(scope)
    working_text = minutes_text(working_minutes) or '0h 00m'
    productivity = round(completed_tasks / members_count, 1) if members_count else 0

    return {
        'projects': len(projects),
        'total_tasks': total,
        'completed_tasks': completed_tasks,
        'in_progress': in_progress_tasks,
        'overdue': len(_overdue_snapshot(scope)[0]),
        'sprint_progress': sprint_progress,
        'sprint_progress_text': sprint_progress_text,
        'average_velocity': velocity['average'],
        'velocity_count': velocity['count'],
        'velocity_total': velocity['total_completed'],
        'velocity_message': velocity['message'],
        'team_workload': team_workload,
        'team_workload_open': open_assigned,
        'team_workload_members': members_count,
        'sprint_completion': sprint_progress,
        'sprint_completion_text': sprint_progress_text,
        'productivity': productivity,
        'productivity_text': (f'{completed_tasks} completed / {members_count} members'
                              if members_count else 'No assigned members'),
        'working_minutes': working_minutes,
        'working_hours': working_text,
    }


def project_health(scope):
    projects = _report_scoped_projects(scope)
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    status_rows = (db.session.query(Issue.project_id, Issue.status, func.count(Issue.id))
                   .filter(*flt).group_by(Issue.project_id, Issue.status).all())
    per = {}
    for pid, status, n in status_rows:
        d = per.setdefault(pid, {'total': 0, 'done': 0, 'in_progress': 0})
        d['total'] += n
        if status == 'done':
            d['done'] += n
        elif status == 'in_progress':
            d['in_progress'] += n

    _, overdue_by_project = _overdue_snapshot(scope)
    working_by_project = _working_minutes_by_project(scope)
    sprint_points = _sprint_aggregate(scope)
    sprints = _report_scoped_sprints(scope)

    rows = []
    for project in projects:
        st = per.get(project.id, {'total': 0, 'done': 0, 'in_progress': 0})
        total = st['total']
        completed = st['done']
        overdue = overdue_by_project.get(project.id, 0)
        progress = round(completed / total * 100) if total else 0
        overdue_pct = round(overdue / total * 100) if total else 0

        active_sprint = None
        for sprint in sprints:
            if sprint.project_id == project.id and sprint.status == 'Active':
                active_sprint = sprint
                break
        sprint_progress = None
        if active_sprint:
            pts = sprint_points.get(active_sprint.id, {'committed': 0, 'completed': 0})
            sprint_progress = round(pts['completed'] / pts['committed'] * 100) if pts['committed'] else 0

        working_minutes = working_by_project.get(project.id, 0)

        rows.append({
            'id': project.id,
            'key': project.key,
            'name': project.name,
            'color': project.color,
            'status': project.status,
            'progress': progress,
            'total_tasks': total,
            'completed': completed,
            'in_progress': st['in_progress'],
            'overdue': overdue,
            'overdue_pct': overdue_pct,
            'current_sprint': active_sprint.name if active_sprint else None,
            'current_sprint_progress': sprint_progress if active_sprint else None,
            'due_date': format_date(project.due_date),
            'health': _report_project_health(total, overdue_pct, progress),
            'working_minutes': working_minutes,
            'working_hours': minutes_text(working_minutes) or None,
        })

    return {'projects': rows}


def sprint_analytics(scope):
    sprints = _report_scoped_sprints(scope)
    stats = _sprint_aggregate(scope)
    working = _working_minutes_by_sprint(scope)

    rows = []
    total_committed = total_completed = total_working = 0
    for sprint in sorted(sprints, key=lambda s: s.number):
        st = stats.get(sprint.id, {'total': 0, 'done': 0, 'in_progress': 0,
                                   'committed': 0, 'completed': 0})
        total = st['total']
        completed_tasks = st['done']
        in_progress_tasks = st['in_progress']
        remaining = total - completed_tasks
        committed = st['committed']
        completed_pts = st['completed']
        if committed:
            total_committed += committed
            total_completed += completed_pts
        working_minutes = working.get(sprint.id, 0)
        total_working += working_minutes
        progress = (round(completed_pts / committed * 100) if committed
                    else (round(completed_tasks / total * 100) if total else 0))
        rows.append({
            'id': sprint.id,
            'name': sprint.name,
            'number': sprint.number,
            'goal': sprint.goal or '',
            'start_date': format_date(sprint.start_date),
            'end_date': format_date(sprint.end_date),
            'status': sprint.status,
            'total_tasks': total,
            'completed_tasks': completed_tasks,
            'in_progress_tasks': in_progress_tasks,
            'remaining_tasks': remaining,
            'committed_points': committed,
            'completed_points': completed_pts,
            'remaining_points': max(committed - completed_pts, 0),
            'progress': progress,
            'duration_days': _days_between(sprint.start_date, sprint.end_date),
            'working_minutes': working_minutes,
            'working_hours': minutes_text(working_minutes) or None,
        })

    return {
        'sprints': rows,
        'total_committed': total_committed,
        'total_completed': total_completed,
        'total_working_minutes': total_working,
        'total_working_hours': minutes_text(total_working) or None,
    }


def velocity(scope):
    return _report_velocity(scope)


def status_distribution(scope):
    counts = _scoped_issue_counts(scope)
    total = sum(counts.values())

    statuses = []
    for st in REPORT_STATUS_ORDER:
        if counts[st]:
            statuses.append({
                'status': st,
                'label': STATUS_LABELS.get(st, st.title()),
                'count': counts[st],
                'color': REPORT_STATUS_COLORS.get(st, '#9ca3af'),
            })
    return {'statuses': statuses, 'total': total}


def priority_distribution(scope):
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    label = func.coalesce(Issue.priority, 'Lowest')
    rows = (db.session.query(label, func.count(Issue.id))
            .filter(*flt).group_by(label).all())
    counts = {p: n for p, n in rows}
    total = sum(counts.values())

    priorities = []
    for p in REPORT_PRIORITY_ORDER:
        if p in counts:
            priorities.append({
                'priority': p,
                'count': counts[p],
                'color': PRIORITY_COLORS.get(p, '#6b7280'),
            })
    return {'priorities': priorities, 'total': total}


def _task_projection_dict(r, projects, sprints, users):
    (iid, number, title, issue_type, status, priority, priority_color, points, due_date,
     completed_at, created_at, project_id, sprint_id, assignee_id,
     assignee_initials, assignee_color) = r
    project = projects.get(project_id)
    project_key = project.key if project else 'PRJ'
    sprint = sprints.get(sprint_id)
    user = users.get(assignee_id)
    return {
        'id': iid,
        'key': f'{project_key}-{number}' if number else f'{project_key}-{iid}',
        'title': (title or '').strip(),
        'status': status,
        'status_label': STATUS_LABELS.get(status, (status or '').title() or ''),
        'status_color': REPORT_STATUS_COLORS.get(status, '#9ca3af'),
        'priority': priority or '',
        'priority_color': priority_color or PRIORITY_COLORS.get(priority, '#6b7280'),
        'points': points or 0,
        'issue_type': issue_type or '',
        'due_date': format_date(due_date),
        'created_at': format_date(created_at),
        'completed_at': completed_at.strftime('%b %d, %Y') if completed_at else None,
        'assignee_id': assignee_id,
        'assignee': user.name if user else None,
        'assignee_initials': (user.initials if user else None) or assignee_initials,
        'assignee_color': (user.color if user else None) or assignee_color or '#9ca3af',
        'sprint_id': sprint_id,
        'sprint': sprint.name if sprint else None,
        'project': project_key,
        'project_name': project.name if project else '',
    }


def overdue(scope):
    today = datetime.utcnow().date()
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    rows = (db.session.query(
                Issue.id, Issue.number, Issue.title, Issue.issue_type, Issue.status,
                Issue.priority, Issue.priority_color, Issue.points, Issue.due_date,
                Issue.completed_at, Issue.created_at, Issue.project_id, Issue.sprint_id,
                Issue.assignee_id, Issue.assignee_initials, Issue.assignee_color,
            ).filter(*flt).all())

    projects = {p.id: p for p in Project.query.all()}
    sprints = {s.id: s for s in Sprint.query.all()}
    users = {u.id: u for u in User.query.all()}

    by_project = {}
    by_assignee = {}
    by_priority = {}
    by_priority_order = {}
    overdue_points = 0
    overdue_issues = []
    upcoming = []

    for r in rows:
        status = r[4]
        due = parse_any_date(r[8])
        if status == 'done' or not due:
            continue
        days_until = (due.date() - today).days
        if days_until < 0:
            overdue_issues.append(r)
            overdue_points += r[7] or 0
            project_key = (projects[r[11]].key if r[11] in projects else '???')
            by_project.setdefault(project_key, {'project': project_key, 'count': 0, 'points': 0})
            by_project[project_key]['count'] += 1
            by_project[project_key]['points'] += r[7] or 0
            by_assignee.setdefault(r[13], {
                'user_id': r[13],
                'name': (users[r[13]].name if r[13] in users else (r[14] or 'Unassigned')),
                'initials': ((users[r[13]].initials if r[13] in users else None) or r[14] or '--'),
                'color': ((users[r[13]].color if r[13] in users else None) or r[15] or '#9ca3af'),
                'count': 0, 'points': 0,
            })
            by_assignee[r[13]]['count'] += 1
            by_assignee[r[13]]['points'] += r[7] or 0
            prio = r[5] or 'Lowest'
            by_priority.setdefault(prio, {'priority': prio, 'count': 0, 'points': 0})
            by_priority[prio]['count'] += 1
            by_priority[prio]['points'] += r[7] or 0
            by_priority_order[prio] = REPORT_PRIORITY_ORDER.index(prio) if prio in REPORT_PRIORITY_ORDER else 99
        elif days_until <= 7:
            upcoming.append({'task': _task_projection_dict(r, projects, sprints, users),
                             'days_until': days_until})

    overdue_issues.sort(key=lambda rr: (parse_any_date(rr[8]) or datetime.max))
    upcoming.sort(key=lambda u: u['days_until'])

    return {
        'total_overdue': len(overdue_issues),
        'overdue_points': overdue_points,
        'by_project': sorted(by_project.values(), key=lambda x: (-x['count'], -x['points'])),
        'by_assignee': sorted(by_assignee.values(), key=lambda x: (-x['count'], -x['points'])),
        'by_priority': [{'priority': k, 'color': PRIORITY_COLORS.get(k, '#6b7280'),
                         'count': v['count'], 'points': v['points']}
                        for k, v in sorted(by_priority.items(), key=lambda kv: (-kv[1]['count'], by_priority_order[kv[0]]))],
        'tasks': [_task_projection_dict(r, projects, sprints, users) for r in overdue_issues],
        'upcoming': upcoming,
        'upcoming_total': len(upcoming),
    }


def completed_over_time(scope):
    hc = _has_children_expr()
    done_scope = ([Issue.status == 'done']
                  + _report_issue_filters(scope, include_status=False)
                  + _report_date_subset_filter(scope))

    done_total = db.session.query(func.count(Issue.id)).filter(*done_scope).scalar() or 0
    done_points = db.session.query(func.coalesce(func.sum(Issue.points), 0)).filter(*done_scope).scalar() or 0

    rows = (db.session.query(
                func.date(Issue.completed_at),
                func.count(Issue.id),
                func.coalesce(func.sum(Issue.points), 0),
                func.coalesce(func.sum(case((
                    db.and_(Issue.working_minutes.isnot(None),
                            db.or_(Issue.parent_issue_id.isnot(None), ~hc)),
                    Issue.working_minutes), else_=0)), 0),
            ).filter(*done_scope, Issue.completed_at.isnot(None))
            .group_by(func.date(Issue.completed_at)).all())

    day_rows = {}
    for d, cnt, pts, wm in rows:
        day_rows[d] = {'tasks': cnt, 'points': int(pts or 0), 'working_minutes': int(wm or 0)}

    stamped_total = sum(r['tasks'] for r in day_rows.values())
    working_total = sum(r['working_minutes'] for r in day_rows.values())

    if not day_rows:
        return {
            'has_completion_data': False,
            'grouping': 'day',
            'series': [],
            'done_total': done_total,
            'done_without_stamp': done_total,
            'total_points': done_points,
            'message': REPORT_DONE_REASON_MSG,
            'working_total_minutes': 0,
            'working_total_hours': None,
            'has_working_data': False,
        }

    dates = sorted(day_rows)
    span_days = (dates[-1] - dates[0]).days
    grouping = 'week' if span_days > 31 else 'day'

    buckets = {}
    for d in dates:
        if grouping == 'week':
            start = d - timedelta(days=d.weekday())
            label = start.strftime('%b %d')
        else:
            start = d
            label = d.strftime('%b %d')
        bucket = buckets.setdefault(start, {
            'label': label, 'start': start.isoformat(),
            'completed_tasks': 0, 'completed_points': 0, 'working_minutes': 0,
        })
        bucket['completed_tasks'] += day_rows[d]['tasks']
        bucket['completed_points'] += day_rows[d]['points']
        bucket['working_minutes'] += day_rows[d]['working_minutes']

    series = []
    for key in sorted(buckets):
        b = buckets[key]
        series.append({
            'label': b['label'],
            'start': b['start'],
            'completed_tasks': b['completed_tasks'],
            'completed_points': b['completed_points'],
            'working_minutes': b['working_minutes'],
            'working_hours': minutes_text(b['working_minutes']) or None,
        })

    return {
        'has_completion_data': True,
        'grouping': grouping,
        'series': series,
        'done_total': done_total,
        'done_without_stamp': done_total - stamped_total,
        'total_points': sum(r['points'] for r in day_rows.values()),
        'message': '',
        'working_total_minutes': working_total,
        'working_total_hours': minutes_text(working_total) if working_total else None,
        'has_working_data': working_total > 0,
    }


def team_performance(scope):
    flt = _report_issue_filters(scope) + _report_date_subset_filter(scope)
    base = db.select(Issue.id).filter(*flt)

    primary = db.select(
        Issue.assignee_id.label('user_id'),
        Issue.id.label('issue_id'),
        Issue.status.label('status'),
        Issue.points.label('points'),
    ).filter(Issue.id.in_(base), Issue.assignee_id.isnot(None))

    linked = (db.select(
        IssueAssignees.user_id.label('user_id'),
        IssueAssignees.issue_id.label('issue_id'),
        Issue.status.label('status'),
        Issue.points.label('points'),
    ).select_from(IssueAssignees)
      .join(Issue, Issue.id == IssueAssignees.issue_id)
      .filter(Issue.id.in_(base)))

    uq = db.union(primary, linked).subquery()
    member_rows = (db.session.query(
        uq.c.user_id,
        func.count(uq.c.issue_id),
        func.coalesce(func.sum(case((uq.c.status == 'done', 1), else_=0)), 0),
        func.coalesce(func.sum(case((uq.c.status == 'in_progress', 1), else_=0)), 0),
        func.coalesce(func.sum(case((uq.c.status == 'done', uq.c.points), else_=0)), 0),
        func.coalesce(func.sum(uq.c.points), 0),
    ).group_by(uq.c.user_id).all())

    overdue_ids, _ = _overdue_snapshot(scope)
    overdue_rows = (db.session.query(uq.c.user_id, uq.c.issue_id)
                    .filter(uq.c.issue_id.in_(overdue_ids)).all())
    overdue_by_user = {}
    for uid, iid in overdue_rows:
        overdue_by_user[uid] = overdue_by_user.get(uid, 0) + 1

    working_by_user = _working_minutes_by_assignee(scope)

    uid_list = [r[0] for r in member_rows]
    users = {u.id: u for u in User.query.filter(User.id.in_(uid_list or [0])).all()}

    members = []
    for uid, assigned, done, in_progress, done_pts, alloc_pts in member_rows:
        u = users.get(uid)
        working_minutes = working_by_user.get(uid, 0)
        members.append({
            'user_id': uid,
            'name': u.name if u else uid,
            'initials': u.initials if u else '--',
            'color': u.color if u else '#9ca3af',
            'role': u.role if u else '',
            'assigned': assigned,
            'completed': int(done or 0),
            'in_progress': int(in_progress or 0),
            'overdue': overdue_by_user.get(uid, 0),
            'completed_points': int(done_pts or 0),
            'allocated_points': int(alloc_pts or 0),
            'working_minutes': working_minutes,
            'working_hours': minutes_text(working_minutes) or '0h 00m',
        })
    members.sort(key=lambda x: (-x['assigned'], str(x['name']).lower()))

    top_contributors = sorted(
        members, key=lambda x: (-x['completed'], str(x['name']).lower()))[:5]

    return {
        'members': members,
        'total_members': len(members),
        'total_assigned': sum(m['assigned'] for m in members),
        'top_contributors': top_contributors,
    }


def drilldown(scope, kind, status, sprint_id):
    title_map = {
        'overdue': 'Overdue Tasks',
        'in_progress': 'In Progress Tasks',
        'status': 'Tasks by Status',
        'velocity': 'Sprint Contribution',
    }
    if kind not in title_map:
        return {'ok': False, 'error': 'Invalid drill-down type.'}, 400
    sprint = None
    if kind == 'status':
        if status and status not in KANBAN_STATUSES:
            return {'ok': False, 'error': 'Invalid status.'}, 400
        if not status:
            status = 'todo'
        issues = [i for i in _report_scoped_issues(scope) if i.status == status]
    elif kind == 'overdue':
        issues = _report_overdue_issues(_report_scoped_issues(scope))
    elif kind == 'in_progress':
        issues = [i for i in _report_scoped_issues(scope) if i.status == 'in_progress']
    elif kind == 'velocity':
        sprint = Sprint.query.get(sprint_id) if sprint_id else None
        if not sprint:
            return {'ok': False, 'error': 'Sprint not found.'}, 404
        if sprint.status != 'Completed':
            return {'ok': False, 'error': 'Velocity drill-down is only available for completed sprints.'}, 400
        if scope['project_id'] and sprint.project_id != scope['project_id']:
            return {'ok': False, 'error': 'Sprint does not belong to the selected project.'}, 400
        q = Issue.query.options(sa_joinedload(Issue.project), sa_joinedload(Issue.sprint),
                                sa_joinedload(Issue.assignee)).filter(Issue.sprint_id == sprint.id)
        if scope['assignee_id']:
            q = _filter_issues_by_assignee(q, scope['assignee_id'])
        if scope['status']:
            q = q.filter(Issue.status == scope['status'])
        issues = q.all()
        if scope['start_date'] or scope['end_date']:
            issues = [i for i in issues if _report_in_date_range(i, scope)]
    else:
        issues = []

    meta = {'status': status, 'sprint': sprint.name if kind == 'velocity' and sprint else None,
            'total_points': sum((i.points or 0) for i in issues if i.status == 'done')} \
        if kind == 'velocity' else {}

    return {
        'type': kind,
        'title': title_map[kind],
        'meta': meta,
        'count': len(issues),
        'tasks': [_report_task_dict(i) for i in issues],
    }, 200