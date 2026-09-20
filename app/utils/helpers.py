"""Shared helpers: serializers, date utils, constants and workspace defaults.

Kept dependency-free of services so both API blueprints and the services
layer can import from here without circular imports.
"""
from datetime import datetime, timedelta
import re

from sqlalchemy import case, func

from app.extensions import db
from app.models import (
    Activity,
    Comment,
    Issue,
    IssueAssignees,
    Project,
    ProjectMembers,
    Sprint,
    User,
    UserNotificationPreferences,
    WorkspaceSettings,
)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def user_dict(u, counts=None):
    now = datetime.utcnow()
    is_online = u.last_seen is not None and (now - u.last_seen) < timedelta(minutes=5)
    if counts is None:
        counts = member_counts([u.id]).get(u.id, {'projects': 0, 'tasks': 0})
    return {'id': u.id, 'name': u.name, 'initials': u.initials, 'role': u.role,
            'team': u.team, 'email': u.email, 'color': u.color, 'plan': u.plan,
            'capacity': u.capacity, 'active_projects': counts['projects'],
            'current_tasks': counts['tasks'], 'status': u.status,
            'is_online': is_online, 'last_seen': u.last_seen.isoformat() if u.last_seen else None,
            'created_at': u.created_at.isoformat() if u.created_at else None}


def member_counts(user_ids=None):
    """Real project-membership and issue-assignment counts per user id.

    Projects come from the project_members join table (a member's "Projects"
    number is their actual membership count). Tasks count DISTINCT issues the
    user is assigned to — either as the primary assignee (issues.assignee_id)
    or through the issue_assignees link table — so historical assignments of
    deactivated members keep counting. Both are single aggregated queries (no
    N+1 per user).

    Returns {user_id: {'projects': int, 'tasks': int}}. When ``user_ids`` is
    provided only those users are returned (defaulting to 0/0).
    """
    proj_rows = (db.session.query(
        ProjectMembers.user_id,
        func.count(ProjectMembers.id),
    ).group_by(ProjectMembers.user_id).all())

    assignment_union = db.union(
        db.select(Issue.assignee_id.label('user_id'), Issue.id.label('issue_id'))
        .where(Issue.assignee_id.isnot(None)),
        db.select(IssueAssignees.user_id.label('user_id'),
                  IssueAssignees.issue_id.label('issue_id')),
    ).subquery()
    task_rows = (db.session.query(
        assignment_union.c.user_id,
        func.count(func.distinct(assignment_union.c.issue_id)),
    ).group_by(assignment_union.c.user_id).all())

    out = {}
    for uid, cnt in proj_rows:
        out.setdefault(uid, {'projects': 0, 'tasks': 0})['projects'] = cnt or 0
    for uid, cnt in task_rows:
        out.setdefault(uid, {'projects': 0, 'tasks': 0})['tasks'] = cnt or 0

    if user_ids is not None:
        return {uid: out.get(uid, {'projects': 0, 'tasks': 0}) for uid in user_ids}
    return out


def project_progress_from_counts(total, completed):
    """Derive the display percentage from raw counts (clamped to 0-100)."""
    if not total:
        return 0
    return max(0, min(100, round(completed / total * 100)))


def project_progress_stats(project_id):
    """Project progress = completed TOP-LEVEL issues / total TOP-LEVEL issues.

    Subtasks (issues with a parent_issue_id) never move the project progress
    meter: only tasks without a parent count towards it. Completed status is
    the app's canonical 'done' value. Both counts come straight from
    PostgreSQL in two aggregate queries (no N+1 issue fetching).
    """
    total = db.session.query(func.count(Issue.id)).filter(
        Issue.project_id == project_id,
        Issue.parent_issue_id.is_(None),
    ).scalar() or 0
    completed = db.session.query(func.count(Issue.id)).filter(
        Issue.project_id == project_id,
        Issue.status == 'done',
        Issue.parent_issue_id.is_(None),
    ).scalar() or 0
    percent = project_progress_from_counts(total, completed)
    return {
        'total_issues': total,
        'completed_issues': completed,
        'progress_percentage': percent,
    }


def project_progress_batch():
    """Counts for every project in a single grouped query.

    Counts TOP-LEVEL tasks only (parent_issue_id IS NULL), matching the
    single project-progress rule. Subtasks are excluded so a project with ten
    subtasks but five real tasks still reports 5 total.

    Returns {project_id: {'total_issues': t, 'completed_issues': d}}.
    """
    rows = (db.session.query(
        Issue.project_id,
        func.count(Issue.id),
        func.sum(case((Issue.status == 'done', 1), else_=0)),
    ).filter(Issue.parent_issue_id.is_(None)).group_by(Issue.project_id).all())
    out = {}
    for pid, total, done in rows:
        out[pid] = {
            'total_issues': total or 0,
            'completed_issues': int(done or 0),
        }
    return out


def project_dict(p, progress_stats=None):
    if progress_stats is None:
        progress_stats = project_progress_stats(p.id)
    total = progress_stats.get('total_issues', 0)
    done = progress_stats.get('completed_issues', 0)
    pct = progress_stats.get('progress_percentage')
    if pct is None:
        pct = project_progress_from_counts(total, done)
    return {
        'id': p.id, 'key': p.key, 'name': p.name, 'lead_id': p.lead_id,
        'lead_initials': p.lead_initials, 'color': p.color, 'status': p.status,
        'classification': p.classification or 'PROJECT',
        'start_date': p.start_date, 'due_date': p.due_date,
        'progress': pct,
        'progress_percentage': pct,
        'total_issues': total,
        'done_issues': done,
        'description': p.description,
        'health': {'schedule': p.health_schedule, 'budget': p.health_budget,
                   'scope': p.health_scope, 'capacity': p.health_capacity},
    }


def minutes_text(minutes):
    """Format a positive minute count as 'Xh Ym'.

    Returns None for missing/zero values so calling views can render an em
    dash ('not recorded') instead of a fake '0h 00m' for tasks that have no
    working hours.
    """
    if not minutes:
        return None
    minutes = int(minutes)
    if minutes <= 0:
        return None
    h, m = divmod(minutes, 60)
    return f'{h}h {m:02d}m'


def issue_dict(i):
    assignee_records = IssueAssignees.query.filter_by(issue_id=i.id).all()
    assignee_users = [User.query.get(r.user_id) for r in assignee_records if User.query.get(r.user_id)]
    all_initials = []
    if i.assignee_initials and i.assignee_initials not in [u.initials for u in assignee_users]:
        all_initials.append(i.assignee_initials)
    all_initials += [u.initials for u in assignee_users]

    parent = None
    if i.parent_issue_id is not None:
        parent = Issue.query.get(i.parent_issue_id)
    subtask_count = 0
    completed_subtasks = 0
    if i.parent_issue_id is None:
        row = (db.session.query(func.count(Issue.id),
                                func.sum(case((Issue.status == 'done', 1), else_=0)))
               .filter(Issue.parent_issue_id == i.id).one())
        subtask_count = row[0] or 0
        completed_subtasks = int(row[1] or 0)

    subtasks = []
    if i.parent_issue_id is None:
        child_rows = (Issue.query.filter_by(parent_issue_id=i.id)
                      .order_by(Issue.subtask_order, Issue.position, Issue.id).all())
        for j, c in enumerate(child_rows, start=1):
            subtasks.append({
                'id': c.id, 'number': c.number,
                'key': f'{c.project.key}-{c.number}' if c.project else f'ECOM-{c.number}',
                'title': c.title, 'status': c.status, 'points': c.points,
                'priority': c.priority, 'priority_color': c.priority_color,
                'type': c.issue_type, 'type_color': c.type_color,
                'sprint': c.sprint.number if c.sprint else None,
                'sprint_name': c.sprint.name if c.sprint else None,
                'due': c.due_date, 'start': c.start_date,
                'working_minutes': c.working_minutes,
                'working_text': minutes_text(c.working_minutes) if c.status == 'done' else None,
                'assignee': c.assignee_initials, 'assignee_color': c.assignee_color,
                'assignee_name': c.assignee.name if c.assignee else None,
                'is_subtask': True, 'parent_issue_id': i.id,
                'parent_key': f'{i.project.key}-{i.number}' if i.project else str(i.number),
                'subtask_order': c.subtask_order or j,
            })

    # Parent tasks with subtasks derive their Working Hours from the completed
    # subtasks (never stored on the parent itself). A task without subtasks
    # simply uses its own recorded minutes. This drives the derived totals on
    # the Project Tasks page and the Task Details working-hours surface.
    if i.parent_issue_id is None and subtask_count > 0:
        _dwm = sum(int(c.get('working_minutes') or 0)
                   for c in subtasks if c.get('status') == 'done')
        derived_total_minutes = _dwm or None
        derived_total_text = minutes_text(derived_total_minutes)
    else:
        derived_total_minutes = i.working_minutes
        derived_total_text = minutes_text(i.working_minutes) if i.status == 'done' else None

    return {
        'id': i.id, 'project': i.project.key if i.project else 'ECOM',
        'number': i.number, 'key': f'{i.project.key}-{i.number}' if i.project else f'ECOM-{i.number}',
        'title': i.title, 'type': i.issue_type, 'type_color': i.type_color,
        'priority': i.priority, 'priority_color': i.priority_color, 'points': i.points,
        'assignee_id': i.assignee_id, 'assignee': i.assignee_initials,
        'assignee_name': i.assignee.name if i.assignee else None,
        'assignee_color': i.assignee_color, 'assignee_initials_list': all_initials,
        'due': i.due_date, 'start': i.start_date,
        'labels': i.labels or [],
        'status': i.status, 'sprint': i.sprint.number if i.sprint else None,
        'sprint_name': i.sprint.name if i.sprint else None,
        'description': i.description, 'acceptance_criteria': i.acceptance_criteria,
        'reporter': i.reporter_id, 'created': i.created_at,
        'working_minutes': i.working_minutes,
        'working_text': minutes_text(i.working_minutes) if i.status == 'done' else None,
        'total_working_minutes': derived_total_minutes,
        'total_working_text': derived_total_text,
        'parent_issue_id': i.parent_issue_id,
        'is_subtask': i.parent_issue_id is not None,
        'subtask_order': i.subtask_order or 0,
        'parent_key': (f'{parent.project.key}-{parent.number}'
                       if parent is not None and parent.project else None),
        'parent_title': parent.title if parent is not None else None,
        'has_subtasks': subtask_count > 0,
        'subtask_count': subtask_count,
        'completed_subtasks': completed_subtasks,
        'subtasks': subtasks,
    }


def sprint_stats_dict(sprint, issues):
    """Build a sprint display dict with task/point stats computed from the
    project's actual issues that belong to this sprint.

    A Sprint is a TIMEBOX. Work items counted here are TOP-LEVEL tasks only:
    subtasks belong to their parent task and are never counted as independent
    sprint items, so a parent + its subtasks are never double-counted.
    (Subtask rows stay in the sprint container via their parent; the raw
    ``tasks`` list below still exposes every issue in the sprint for tooling.)
    """
    sp_issues = [i for i in issues if i.sprint_id == sprint.id]
    # Top-level only for all task/point accounting (no double counting).
    plan = [i for i in sp_issues if i.parent_issue_id is None]
    story_points_total = sum(i.points or 0 for i in plan)
    story_points_done = sum((i.points or 0) for i in plan if i.status == 'done')
    backlog = sum(1 for i in plan if i.status == 'backlog')
    to_do = sum(1 for i in plan if i.status == 'todo')
    in_progress = sum(1 for i in plan if i.status == 'in_progress')
    in_review = sum(1 for i in plan if i.status == 'in_review')
    done = sum(1 for i in plan if i.status == 'done')
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
# Dashboard helpers (all project-scoped, derived from real records)
# ---------------------------------------------------------------------------

def project_member_count(project):
    """Count the actual members of a project from the membership table."""
    if project is None:
        return 0
    return ProjectMembers.query.filter_by(project_id=project.id).count()


def active_project_sprint(project):
    """Return the active sprint for a project using the application's
    established rule (sprint status == 'Active'), falling back to the first
    active sprint if more than one exists."""
    if project is None:
        return None
    return (Sprint.query
            .filter_by(project_id=project.id, status='Active')
            .order_by(Sprint.number)
            .first())


def open_issue_count(issues):
    """Issues that are not completed (Done is the only closed status)."""
    return sum(1 for i in issues if i.status != 'done')


def this_week_bounds():
    """Monday..Sunday of the current week, computed dynamically."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def tasks_due_this_week(issues):
    """Count not-done issues whose due date falls inside the current week.

    Issues without a parseable due date (or without one at all) are skipped.
    """
    start, end = this_week_bounds()
    count = 0
    for i in issues:
        if i.status == 'done':
            continue
        due = parse_any_date(i.due_date)
        if due and start <= due.date() <= end:
            count += 1
    return count


def sprint_progress_pct(stats):
    """Story-point based progress for a sprint stats dict; 0 when no points."""
    if not stats:
        return 0
    total = stats.get('story_points_total') or 0
    if not total:
        return 0
    return round((stats.get('story_points_done') or 0) / total * 100)


def _relative_time(dt, day_only=False):
    """Human relative time, recomputed from the recorded timestamp.

    ``day_only=True`` is used for records whose timestamp has day precision
    only (created_at / comment created_at), so the label never implies a
    false sub-day precision (e.g. a comment added just now is 'today',
    not '6 hours ago').
    """
    if dt is None:
        return ''
    now = datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    if day_only:
        days = (now.date() - dt.date()).days
        if days <= 0:
            return 'today'
        if days == 1:
            return 'yesterday'
        if days < 7:
            return f'{days} days ago'
        return dt.strftime('%b %d, %Y')
    diff = now - dt
    if diff < timedelta(minutes=1):
        return 'just now'
    if diff < timedelta(hours=1):
        mins = max(int(diff.total_seconds() // 60), 1)
        return f'{mins} min ago'
    if diff < timedelta(days=1):
        hours = int(diff.total_seconds() // 3600)
        return '1 hour ago' if hours == 1 else f'{hours} hours ago'
    if diff < timedelta(days=7):
        days = diff.days
        return '1 day ago' if days == 1 else f'{days} days ago'
    return dt.strftime('%b %d, %Y')


def _activity_issue_key(text):
    """Parse '<Actor> moved <KEY> to <Label>' from an activity text.

    Returns (issue_key, status) or (None, None) when the row is not a
    status-change activity (e.g. the seed rows for comments/assignments).
    """
    m = re.match(r'^.*\bmoved\s+([A-Z]{1,6}-\d+)\s+to\s+(.+?)\s*$', str(text or '').strip())
    if not m:
        return None, None
    key, label = m.group(1), m.group(2).strip()
    status = {v: k for k, v in STATUS_LABELS.items()}.get(label)
    if status is None:
        return None, None
    return key, status


def _activity_time(value):
    """Parse a stored activity timestamp.

    Returns None for the seed rows, which store stale display strings such
    as '2h ago' / '8h ago' instead of a real timestamp.
    """
    if not value:
        return None
    s = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _issue_from_key(key):
    """Resolve a key like 'ECOM-168' back to a real Issue row (or None)."""
    m = re.match(r'^([A-Z]{1,6})-(\d+)$', key)
    if not m:
        return None
    project = Project.query.filter_by(key=m.group(1)).first()
    if not project:
        return None
    return Issue.query.filter_by(project_id=project.id, number=int(m.group(2))).first()


def recent_activity(project=None, limit=8):
    """Build the Recent Activity feed from real records only, newest first.

    Sources (no fabricated history):
      - issue created            -> Issue.created_at + reporter
      - issue completed          -> Issue.completed_at
      - comment created          -> Comment.created_at + author
      - issue status changed     -> existing Activity table rows that the
                                    service layer writes on a real status
                                    change (seeded rows carry only stale
                                    display strings and are never matched)

    Every displayed name / issue key comes from a real row and every relative
    timestamp is recomputed from the recorded timestamp at render time.
    """
    issues_q = Issue.query
    if project is not None:
        issues_q = issues_q.filter_by(project_id=project.id)
    issues = issues_q.all()

    comments_q = Comment.query.join(Issue, Issue.id == Comment.issue_id)
    if project is not None:
        comments_q = comments_q.filter(Issue.project_id == project.id)
    comments = comments_q.all()

    events = []
    for i in issues:
        created = parse_any_date(i.created_at)
        if created:
            reporter = User.query.get(i.reporter_id) if i.reporter_id else None
            events.append({
                'sort': created,
                'icon': 'plus',
                'color': '#4f46e5',
                'text': f"{(reporter.name if reporter else 'Someone')} created {issue_ref(i)}",
                'detail': i.title,
                'time': _relative_time(created, day_only=True),
            })
        if i.completed_at:
            item = {
                'sort': i.completed_at,
                'icon': 'check',
                'color': '#059669',
                'text': f'{issue_ref(i)} moved to Done',
                'detail': i.title,
                'time': _relative_time(i.completed_at),
            }
            item['_dedup_key'] = issue_ref(i)
            item['_completed'] = True
            events.append(item)
    for c in comments:
        created = parse_any_date(c.created_at)
        issue = Issue.query.get(c.issue_id)
        if created and issue:
            author = User.query.get(c.author_id) if c.author_id else None
            events.append({
                'sort': created,
                'icon': 'comment',
                'color': '#059669',
                'text': f"{(author.name if author else 'Someone')} commented on {issue_ref(issue)}",
                'detail': comment_preview(c.body),
                'time': _relative_time(created, day_only=True),
            })

    # Status-change activities recorded by the application (existing Activity
    # table). Rows without a real timestamp (seed rows) or that do not follow
    # the 'moved <KEY> to <Status>' pattern are ignored. A real 'moved to
    # Done' activity replaces the completed_at event for the same issue so the
    # transition is only shown once.
    done_keys = set()
    for a in Activity.query.order_by(Activity.id).all():
        key, status = _activity_issue_key(a.text)
        if not key or status is None:
            continue
        ts = _activity_time(a.time)
        if ts is None:
            continue
        issue = _issue_from_key(key)
        if issue is None or (project is not None and issue.project_id != project.id):
            continue
        events.append({
            'sort': ts,
            'icon': a.icon or 'arrow',
            'color': a.color or '#d97706',
            'text': a.text[:240],
            'detail': a.detail or issue.title,
            'time': _relative_time(ts),
        })
        if status == 'done':
            done_keys.add(key)

    if done_keys:
        events = [e for e in events
                  if not (e.get('_completed') and e.get('_dedup_key') in done_keys)]
    for e in events:
        e.pop('_dedup_key', None)
        e.pop('_completed', None)

    events.sort(key=lambda e: e['sort'], reverse=True)
    for idx, ev in enumerate(events[:limit]):
        ev['id'] = idx + 1
    return events[:limit]


# ---------------------------------------------------------------------------
# Context helpers (page rendering)
# ---------------------------------------------------------------------------

SELECTED_PROJECT_SESSION_KEY = 'selected_project_id'
SELECTED_PROJECT_LS_KEY = 'selectedProjectId'


def _persisted_project_id():
    """Read the persisted selected-project id (Flask session), or None."""
    from flask import session
    try:
        pid = session.get(SELECTED_PROJECT_SESSION_KEY)
        return int(pid) if pid not in (None, '') else None
    except (TypeError, ValueError):
        return None


def resolve_selected_project(key=None):
    """Resolve the canonical selected project (single source of truth).

    Priority:
      1. explicit project KEY from the URL (?project= or /kanban/<key>) —
         authoritative for that page, persisted to the session;
      2. the persisted selected_project_id in the authenticated Flask session;
      3. the first accessible project — ONLY when nothing has ever been chosen.

    The resolved project id is written back to the session so the selection
    survives navigation, browser refresh and back/forward browsing. Falls back
    gracefully (never crashes, never silently shows a random different project)
    and removes invalid persisted ids per the requirement.
    """
    from flask import session

    project = None
    if key:
        k = str(key).strip().upper()
        if k:
            project = Project.query.filter_by(key=k).first()

    if project is None:
        pid = _persisted_project_id()
        if pid is not None:
            project = Project.query.filter_by(id=pid).first()

    if project is None:
        project = Project.query.order_by(Project.id).first()

    if project is not None:
        session[SELECTED_PROJECT_SESSION_KEY] = project.id
    return project


def context_project(key=''):
    """Project for a project-scoped page.

    An explicit URL key is authoritative; otherwise the persisted selected
    project is restored (session), falling back to the first project only when
    no selection has ever been made. A missing/empty key is treated as "no
    explicit choice", so navigation never silently resets to project #1.
    """
    return resolve_selected_project(key)


def context_sprints(project):
    return Sprint.query.filter_by(project_id=project.id).order_by(Sprint.number).all()


def context_issues(project):
    return Issue.query.filter_by(project_id=project.id).order_by(Issue.position).all()


def issue_hierarchy(issues):
    """Split a project's issues into top-level Tasks and their Subtasks.

    Returns (top_level, children_map):
      * top_level   — issues whose parent_issue_id is NULL, in list order.
      * children_map— {parent_issue_id: [subtask Issue, ...]} ordered by
                       (subtask_order, position, id). One level of nesting only,
                       matching the single-level Subtask rule enforced by the
                       service layer.
    """
    children_map = {}
    top_level = []
    for i in issues:
        if i.parent_issue_id is not None:
            children_map.setdefault(i.parent_issue_id, []).append(i)
        else:
            top_level.append(i)
    for pid in children_map:
        children_map[pid].sort(key=lambda c: (c.subtask_order or 0, c.position or 0, c.id))
    return top_level, children_map


def subtask_display_key(parent, index):
    """Visual key for a subtask row: '<PARENT-KEY>-<n>' (display only).

    The stored issue number/key is never rewritten; this only labels the
    nested row alongside the parent, e.g. ECOM-142-1 for the first subtask.
    """
    if parent is None:
        return str(index)
    base = f'{parent.project.key}-{parent.number}' if parent.project else str(parent.number)
    return f'{base}-{index}'


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


def calculate_duration(start_date, end_date):
    """Calendar-day difference between two dates (Target Date - Start Date).

    Dates are normalized (parsed to midnight) and compared by calendar day,
    so the result never varies with the time of day. Returns None when either
    date cannot be parsed.
    """
    s = parse_date(start_date)
    e = parse_date(end_date)
    if s is None or e is None:
        return None
    return (e.date() - s.date()).days


def determine_classification(start_date, end_date):
    """Duration-based classification for a Project record.

    More than 4 days        -> 'PROJECT'
    4 days or fewer         -> 'TO DO'
    Missing/unparseable date-> 'PROJECT' (safe default; Project entity)
    """
    days = calculate_duration(start_date, end_date)
    if days is not None and days <= 4:
        return 'TO DO'
    return 'PROJECT'


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


# ---------------------------------------------------------------------------
# Sidebar section mapping
# ---------------------------------------------------------------------------
# Maps every HTML page endpoint to the sidebar section that must stay active
# while that page (or any of its child/detail routes) is open. Matching uses
# the Flask endpoint name (the route identity), so it works for direct URLs,
# refreshes, Back/Forward navigation and query-string variants alike, and it
# cannot collide like raw path prefixes (/project vs /projects).
#
# A section stays active across its whole subtree:
#   Projects  -> /projects, /project, /project/<key>, /issue, /issue/<id>
#   Kanban    -> /kanban, /kanban/<key>
#   Backlog   -> /backlog, /backlog/<key>
#   Sprints   -> /sprints, /sprints/<key>
#   Team      -> /team, /people-hub
SIDEBAR_SECTION_BY_ENDPOINT = {
    'dashboard': 'dashboard',
    'projects': 'projects',
    'project_overview': 'projects',
    'issue_detail': 'projects',
    'issue_default': 'projects',
    'my_work': 'my_work',
    'kanban': 'kanban',
    'backlog': 'backlog',
    'sprints': 'sprints',
    'ai_assistant': 'ai-assistant',
    'reports': 'reports',
    'team': 'team',
    'people_hub': 'team',
    'notifications': 'notifications',
}


def active_section_for(endpoint):
    """Return the sidebar section (nav key) active for a page endpoint.

    Returns ``None`` for endpoints with no sidebar representation (auth,
    static, swagger, redirects) so exactly one nav item is active at a time.
    """
    return SIDEBAR_SECTION_BY_ENDPOINT.get(endpoint)


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