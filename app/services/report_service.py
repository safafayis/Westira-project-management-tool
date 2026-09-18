"""Reports & analytics business logic.

The report scope (project/sprint/assignee/status/date filters) is parsed and
validated in the API layer; every function here computes over that scope dict.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import aliased as sa_aliased
from sqlalchemy.orm import joinedload as sa_joinedload

from app.extensions import db
from app.models import Issue, IssueAssignees, Project, Sprint, User
from app.utils.helpers import (
    KANBAN_STATUSES,
    PRIORITY_COLORS,
    STATUS_LABELS,
    format_date,
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
    """Issues matching the report scope. Project/sprint/assignee/status filters run in
    SQL; the date-range filter runs in Python because dates are stored as strings in
    multiple formats. Relationships are eager-loaded to avoid N+1 queries."""
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


def _report_issues_by_sprint(scope, sprints):
    """Map of sprint_id -> list of scoped issues, one query (no per-sprint N+1)."""
    if not sprints:
        return {}
    sprint_ids = [s.id for s in sprints]
    q = Issue.query.options(sa_joinedload(Issue.assignee)).filter(Issue.sprint_id.in_(sprint_ids))
    if scope['project_id']:
        q = q.filter(Issue.project_id == scope['project_id'])
    if scope['assignee_id']:
        q = _filter_issues_by_assignee(q, scope['assignee_id'])
    if scope['status']:
        q = q.filter(Issue.status == scope['status'])
    rows = q.all()
    if scope['start_date'] or scope['end_date']:
        rows = [i for i in rows if _report_in_date_range(i, scope)]
    by_sprint = {}
    for issue in rows:
        by_sprint.setdefault(issue.sprint_id, []).append(issue)
    return by_sprint


def _report_sprint_points(sprint, by_sprint):
    issues = by_sprint.get(sprint.id, [])
    committed = sum((i.points or 0) for i in issues)
    completed = sum((i.points or 0) for i in issues if i.status == 'done')
    return committed, completed


def _report_overdue_issues(issues):
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
    by_sprint = _report_issues_by_sprint(scope, completed_sprints)
    rows = []
    weighted = 0
    total_completed = 0
    for sprint in sorted(completed_sprints, key=lambda s: s.number):
        committed, completed_pts = _report_sprint_points(sprint, by_sprint)
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


def _project_health(project, total, completed, overdue, sprint_progress):
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
    if project.status and project.status.lower() != 'completed' and project.progress < 100:
        due = parse_any_date(project.due_date)
        if due:
            days_left = (due.date() - datetime.utcnow().date()).days
            if 0 <= days_left <= 14:
                return 'Critical'
            if days_left <= 30:
                return 'At Risk'
    return 'Healthy'


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
    issues = _report_scoped_issues(scope)
    overdue = _report_overdue_issues(issues)

    total = len(issues)
    completed_tasks = sum(1 for i in issues if i.status == 'done')
    in_progress_tasks = sum(1 for i in issues if i.status == 'in_progress')

    by_sprint = _report_issues_by_sprint(scope, sprints)
    committed_points = sum(sum((i.points or 0) for i in by_sprint.get(s.id, [])) for s in sprints)
    completed_points = sum(sum((i.points or 0) for i in by_sprint.get(s.id, []) if i.status == 'done')
                           for s in sprints)
    sprint_progress = round(completed_points / committed_points * 100) if committed_points else 0
    sprint_progress_text = (f'{completed_points} / {committed_points} story points'
                            if committed_points else 'No sprint work in scope')

    velocity = _report_velocity(scope, sprints)

    open_assigned = [i for i in issues if i.status != 'done' and (i.assignee_id or i.assignee_initials)]
    member_ids = {i.assignee_id for i in issues if i.assignee_id}
    members_count = len(member_ids)
    team_workload = round(len(open_assigned) / members_count, 1) if members_count else 0

    return {
        'projects': len(projects),
        'total_tasks': total,
        'completed_tasks': completed_tasks,
        'in_progress': in_progress_tasks,
        'overdue': len(overdue),
        'sprint_progress': sprint_progress,
        'sprint_progress_text': sprint_progress_text,
        'average_velocity': velocity['average'],
        'velocity_count': velocity['count'],
        'velocity_total': velocity['total_completed'],
        'velocity_message': velocity['message'],
        'team_workload': team_workload,
        'team_workload_open': len(open_assigned),
        'team_workload_members': members_count,
    }


def project_health(scope):
    projects = _report_scoped_projects(scope)
    sprints = _report_scoped_sprints(scope)
    issues_by_project = {}
    for issue in _report_scoped_issues(scope):
        issues_by_project.setdefault(issue.project_id, []).append(issue)
    by_sprint = _report_issues_by_sprint(scope, sprints)

    rows = []
    for project in projects:
        p_issues = issues_by_project.get(project.id, [])
        total = len(p_issues)
        completed = sum(1 for i in p_issues if i.status == 'done')
        in_progress = sum(1 for i in p_issues if i.status == 'in_progress')
        overdue = len(_report_overdue_issues(p_issues))
        progress = round(completed / total * 100) if total else (project.progress or 0)

        active_sprint = None
        for sprint in sprints:
            if sprint.project_id == project.id and sprint.status == 'Active':
                active_sprint = sprint
                break
        sprint_progress = None
        if active_sprint:
            committed, completed_pts = _report_sprint_points(active_sprint, by_sprint)
            sprint_progress = round(completed_pts / committed * 100) if committed else 0

        rows.append({
            'id': project.id,
            'key': project.key,
            'name': project.name,
            'color': project.color,
            'status': project.status,
            'progress': progress,
            'total_tasks': total,
            'completed': completed,
            'in_progress': in_progress,
            'overdue': overdue,
            'current_sprint': active_sprint.name if active_sprint else None,
            'current_sprint_progress': sprint_progress if active_sprint else None,
            'due_date': format_date(project.due_date),
            'health': _project_health(project, total, completed, overdue, sprint_progress),
        })

    return {'projects': rows}


def sprint_analytics(scope):
    sprints = _report_scoped_sprints(scope)
    by_sprint = _report_issues_by_sprint(scope, sprints)

    rows = []
    total_committed = total_completed = 0
    for sprint in sorted(sprints, key=lambda s: s.number):
        sp_issues = by_sprint.get(sprint.id, [])
        total = len(sp_issues)
        completed_tasks = sum(1 for i in sp_issues if i.status == 'done')
        in_progress_tasks = sum(1 for i in sp_issues if i.status == 'in_progress')
        remaining = total - completed_tasks
        committed, completed_pts = _report_sprint_points(sprint, by_sprint)
        if committed:
            total_committed += committed
            total_completed += completed_pts
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
        })

    return {'sprints': rows, 'total_committed': total_committed, 'total_completed': total_completed}


def velocity(scope):
    return _report_velocity(scope)


def status_distribution(scope):
    issues = _report_scoped_issues(scope)
    counts = {}
    for issue in issues:
        counts[issue.status] = counts.get(issue.status, 0) + 1

    statuses = []
    for st in REPORT_STATUS_ORDER:
        if st in counts:
            statuses.append({
                'status': st,
                'label': STATUS_LABELS.get(st, st.title()),
                'count': counts[st],
                'color': REPORT_STATUS_COLORS.get(st, '#9ca3af'),
            })
    return {'statuses': statuses, 'total': len(issues)}


def priority_distribution(scope):
    issues = _report_scoped_issues(scope)
    counts = {}
    for issue in issues:
        p = issue.priority or 'Lowest'
        counts[p] = counts.get(p, 0) + 1

    priorities = []
    for p in REPORT_PRIORITY_ORDER:
        if p in counts:
            priorities.append({
                'priority': p,
                'count': counts[p],
                'color': PRIORITY_COLORS.get(p, '#6b7280'),
            })
    return {'priorities': priorities, 'total': len(issues)}


def overdue(scope):
    issues = _report_scoped_issues(scope)
    overdue_issues = _report_overdue_issues(issues)

    by_project = {}
    by_assignee = {}
    by_priority = {}
    by_priority_order = {}
    overdue_points = 0
    for issue in overdue_issues:
        overdue_points += issue.points or 0
        key = issue.project.key if issue.project else '???'
        by_project.setdefault(key, {'project': key, 'count': 0, 'points': 0})
        by_project[key]['count'] += 1
        by_project[key]['points'] += issue.points or 0
        by_assignee.setdefault(issue.assignee_id, {
            'user_id': issue.assignee_id,
            'name': issue.assignee.name if issue.assignee else (issue.assignee_initials or 'Unassigned'),
            'initials': (issue.assignee.initials if issue.assignee else None) or issue.assignee_initials or '--',
            'color': (issue.assignee.color if issue.assignee else None) or issue.assignee_color or '#9ca3af',
            'count': 0, 'points': 0,
        })
        by_assignee[issue.assignee_id]['count'] += 1
        by_assignee[issue.assignee_id]['points'] += issue.points or 0
        prio = issue.priority or 'Lowest'
        by_priority.setdefault(prio, {'priority': prio, 'count': 0, 'points': 0})
        by_priority[prio]['count'] += 1
        by_priority[prio]['points'] += issue.points or 0
        by_priority_order[prio] = REPORT_PRIORITY_ORDER.index(prio) if prio in REPORT_PRIORITY_ORDER else 99

    today = datetime.utcnow().date()
    upcoming = []
    for issue in issues:
        if issue.status == 'done':
            continue
        due = parse_any_date(issue.due_date)
        if not due:
            continue
        days_until = (due.date() - today).days
        if 0 <= days_until <= 7:
            upcoming.append({'task': _report_task_dict(issue), 'days_until': days_until})
    upcoming.sort(key=lambda u: u['days_until'])

    return {
        'total_overdue': len(overdue_issues),
        'overdue_points': overdue_points,
        'by_project': sorted(by_project.values(), key=lambda x: (-x['count'], -x['points'])),
        'by_assignee': sorted(by_assignee.values(), key=lambda x: (-x['count'], -x['points'])),
        'by_priority': [{'priority': k, 'color': PRIORITY_COLORS.get(k, '#6b7280'),
                         'count': v['count'], 'points': v['points']}
                        for k, v in sorted(by_priority.items(), key=lambda kv: (-kv[1]['count'], by_priority_order[kv[0]]))],
        'tasks': [_report_task_dict(i) for i in overdue_issues],
        'upcoming': upcoming,
        'upcoming_total': len(upcoming),
    }


def completed_over_time(scope):
    issues = _report_scoped_issues(scope)
    completed = [i for i in issues if i.status == 'done']
    stamped = [i for i in completed if i.completed_at]

    if not stamped:
        return {
            'has_completion_data': False,
            'grouping': 'day',
            'series': [],
            'done_total': len(completed),
            'done_without_stamp': len(completed),
            'total_points': sum((i.points or 0) for i in completed),
            'message': REPORT_DONE_REASON_MSG,
        }

    stamps = sorted(i.completed_at for i in stamped)
    span_days = (stamps[-1].date() - stamps[0].date()).days
    grouping = 'week' if span_days > 31 else 'day'

    buckets = {}
    for issue in stamped:
        if grouping == 'week':
            start = issue.completed_at.date() - timedelta(days=issue.completed_at.weekday())
            key = start  # week start (Monday)
            label = start.strftime('%b %d')
        else:
            key = issue.completed_at.date()
            label = issue.completed_at.strftime('%b %d')
        bucket = buckets.setdefault(key, {'label': label, 'start': key.isoformat() if isinstance(key, object) else '', 'completed_tasks': 0, 'completed_points': 0})
        bucket['completed_tasks'] += 1
        bucket['completed_points'] += issue.points or 0

    series = [buckets[k] for k in sorted(buckets)]
    return {
        'has_completion_data': True,
        'grouping': grouping,
        'series': series,
        'done_total': len(completed),
        'done_without_stamp': len(completed) - len(stamped),
        'total_points': sum((i.points or 0) for i in stamped),
        'message': '',
    }


def team_performance(scope):
    issues = _report_scoped_issues(scope)
    if not issues:
        return {'members': [], 'total_members': 0, 'total_assigned': 0}

    issue_ids = [i.id for i in issues]
    link_rows = (db.session.query(IssueAssignees)
                 .filter(IssueAssignees.issue_id.in_(issue_ids)).all())
    links_by_issue = {}
    for row in link_rows:
        links_by_issue.setdefault(row.issue_id, []).append(row.user_id)

    members = {}
    overdue_issues = set(id(i) for i in _report_overdue_issues(issues))
    for issue in issues:
        uids = set()
        if issue.assignee_id:
            uids.add(issue.assignee_id)
        for uid in links_by_issue.get(issue.id, []):
            uids.add(uid)
        for uid in uids:
            m = members.setdefault(uid, {
                'user_id': uid, 'assigned': 0, 'completed': 0,
                'in_progress': 0, 'overdue': 0,
                'completed_points': 0, 'allocated_points': 0,
            })
            m['assigned'] += 1
            m['allocated_points'] += issue.points or 0
            if issue.status == 'done':
                m['completed'] += 1
                m['completed_points'] += issue.points or 0
            elif issue.status == 'in_progress':
                m['in_progress'] += 1
            if id(issue) in overdue_issues:
                m['overdue'] += 1

    users = {u.id: u for u in User.query.filter(User.id.in_(list(members))).all()}
    rows = []
    for uid, m in members.items():
        u = users.get(uid)
        rows.append({
            'user_id': uid,
            'name': u.name if u else uid,
            'initials': u.initials if u else '--',
            'color': u.color if u else '#9ca3af',
            'role': u.role if u else '',
            'assigned': m['assigned'],
            'completed': m['completed'],
            'in_progress': m['in_progress'],
            'overdue': m['overdue'],
            'completed_points': m['completed_points'],
            'allocated_points': m['allocated_points'],
        })
    rows.sort(key=lambda x: (-x['assigned'], x['name'].lower()))

    return {
        'members': rows,
        'total_members': len(rows),
        'total_assigned': sum(r['assigned'] for r in rows),
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