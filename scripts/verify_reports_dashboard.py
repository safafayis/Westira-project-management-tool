"""End-to-end verification of the Reports & Analytics dashboard rewrite.

Asserts (against a live test client, login alex@abc.io / password123):
  * backend contract of every report endpoint — both the pre-existing shape
    checks from verify_full_run.py and the new SQL-aggregated fields
    (working hours, productivity, sprint completion, top contributors,
    per-sprint duration/working hours, completed-over-time totals);
  * health threshold rule (unit check of _report_project_health);
  * filter scoping (project/assignee/date) reaches the service layer;
  * the reports page keeps the required literals and drops the removed ones.
"""
import sys

sys.path.insert(0, r'C:\Users\SAFA FAYIS\sample_flaskapi_api')
from app import create_app

app = create_app()
c = app.test_client()


def _fmt(minutes):
    minutes = int(minutes or 0)
    if minutes <= 0:
        return '0h 00m'
    h, m = divmod(minutes, 60)
    return f'{h}h {m:02d}m'


login = c.post('/login', json={'email': 'alex@abc.io', 'password': 'password123'})
PASS = []
FAIL = []


def check(name, ok, extra=''):
    (PASS if ok else FAIL).append(name)
    status = 'PASS' if ok else 'FAIL'
    print(f'[{status}] {name}' + (f'  -> {extra}' if extra and not ok else ''))


check('reports verifier login', login.status_code == 200, f'status={login.status_code}')

# ---------------------------------------------------------------------------
# KPI / summary — new SQL-aggregated fields present and sane
# ---------------------------------------------------------------------------
r = c.get('/api/v1/reports/summary')
s = r.get_json() or {}
needed = ['total_tasks', 'completed_tasks', 'in_progress', 'overdue',
          'sprint_progress', 'average_velocity', 'velocity_count', 'team_workload',
          'sprint_completion', 'sprint_completion_text', 'productivity',
          'productivity_text', 'working_minutes', 'working_hours']
check('GET /api/v1/reports/summary -> 200 + fields', r.status_code == 200
      and all(k in s for k in needed), f'status={r.status_code} keys={sorted(s)}')
check('summary counts are non-negative ints',
      all(isinstance(s.get(k), int) and s.get(k) >= 0
          for k in ('total_tasks', 'completed_tasks', 'in_progress', 'overdue',
                    'working_minutes')),
      str({k: s.get(k) for k in ('total_tasks', 'completed_tasks', 'overdue', 'working_minutes')}))
check('summary working hours == minutes_text(working_minutes)',
      s.get('working_hours') == _fmt(s.get('working_minutes')),
      f'{s.get("working_hours")} vs {_fmt(s.get("working_minutes"))}')
check('summary sprint_completion mirrors sprint_progress',
      s.get('sprint_completion') == s.get('sprint_progress')
      and s.get('sprint_completion_text') == s.get('sprint_progress_text'),
      f'{s.get("sprint_completion")} vs {s.get("sprint_progress")}')

# ---------------------------------------------------------------------------
# Project health — new fields + internal consistency
# ---------------------------------------------------------------------------
r = c.get('/api/v1/reports/project-health')
ph = r.get_json() or {}
rows = ph.get('projects', [])
check('GET /api/v1/reports/project-health -> 200 + rows', r.status_code == 200
      and isinstance(rows, list) and len(rows) >= 1, f'status={r.status_code} n={len(rows)}')
check('project-health rows carry new fields',
      bool(rows) and all('health' in p and 'overdue_pct' in p and 'working_hours' in p
                         and 'working_minutes' in p for p in rows),
      str([{k: p.get(k) for k in ('key', 'health', 'overdue_pct')} for p in rows])[:200])
check('project-health semantics: progress==round(done/total), overdue_pct==round(overdue/total)',
      all(round(p['completed'] / p['total_tasks'] * 100) == p['progress']
          and round(p['overdue'] / p['total_tasks'] * 100) == p['overdue_pct']
          for p in rows if p['total_tasks'] > 0),
      str([(p['key'], p['progress'], p['overdue_pct']) for p in rows])[:200])
check('project-health has Healthy/Warning/Critical values only',
      all(p['health'] in ('Healthy', 'Warning', 'Critical') for p in rows),
      str({p['key']: p['health'] for p in rows}))

# ---------------------------------------------------------------------------
# Sprint analytics — per-sprint data + totals
# ---------------------------------------------------------------------------
r = c.get('/api/v1/reports/sprint-analytics')
sa = r.get_json() or {}
sprouts = sa.get('sprints', [])
check('GET /api/v1/reports/sprint-analytics -> 200 + totals',
      r.status_code == 200 and 'total_committed' in sa and 'total_completed' in sa
      and 'total_working_minutes' in sa and 'total_working_hours' in sa,
      f'status={r.status_code}')
check('sprint rows carry duration/working fields',
      bool(sprouts) and all('duration_days' in sp and 'working_minutes' in sp
                            and 'working_hours' in sp for sp in sprouts),
      str([(sp['name'], sp.get('duration_days'), sp.get('working_hours')) for sp in sprouts])[:200])
check('sprint working totals == sum of rows',
      (sa.get('total_working_minutes') or 0) == sum((sp.get('working_minutes') or 0) for sp in sprouts),
      f"{sa.get('total_working_minutes')} vs {sum((sp.get('working_minutes') or 0) for sp in sprouts)}")

# ---------------------------------------------------------------------------
# Completed over time — working-hours series + totals
# ---------------------------------------------------------------------------
r = c.get('/api/v1/reports/completed-over-time')
cot = r.get_json() or {}
check('GET /api/v1/reports/completed-over-time -> 200',
      r.status_code == 200 and 'has_completion_data' in cot, f'status={r.status_code}')
for key in ('working_total_minutes', 'working_total_hours', 'has_working_data',
            'done_total', 'done_without_stamp', 'total_points', 'series'):
    check(f'completed-over-time keeps key: {key}', key in cot,
          str(sorted(cot))[:200])
if cot.get('has_completion_data'):
    series = cot.get('series', [])
    check('completed-over-time buckets carry working_minutes/hours',
          bool(series) and all('working_minutes' in b and 'working_hours' in b
                               and b['working_minutes'] >= 0 for b in series),
          str(series[:1])[:200])
    check('completed-over-time working total == sum of buckets',
          (cot.get('working_total_minutes') or 0) == sum(b.get('working_minutes') or 0 for b in series),
          f"{cot.get('working_total_minutes')} vs {sum(b.get('working_minutes') or 0 for b in series)}")
    check('completed-over-time has_working_data flag consistent',
          bool(cot.get('has_working_data')) == bool(cot.get('working_total_minutes')),
          f"flag={cot.get('has_working_data')} mins={cot.get('working_total_minutes')}")

# ---------------------------------------------------------------------------
# Team performance — top contributors + per-member working hours
# ---------------------------------------------------------------------------
r = c.get('/api/v1/reports/team-performance')
tp = r.get_json() or {}
members = tp.get('members', [])
tops = tp.get('top_contributors', [])
check('GET /api/v1/reports/team-performance -> 200 + top_contributors',
      r.status_code == 200 and isinstance(tops, list) and isinstance(members, list),
      f'status={r.status_code}')
check('top_contributors: max 5, subset of members, sorted by completed desc',
      len(tops) <= 5
      and ({m['user_id'] for m in tops} <= {m['user_id'] for m in members})
      and all(tops[i]['completed'] >= tops[i + 1]['completed'] for i in range(len(tops) - 1)),
      str([(m['name'], m['completed']) for m in tops])[:200])
check('team members carry working_minutes/hours',
      bool(members) and all('working_minutes' in m and 'working_hours' in m for m in members),
      str([(m['name'], m.get('working_hours')) for m in members])[:200])
check('team totals consistent',
      tp.get('total_members') == len(members)
      and tp.get('total_assigned') == sum(m['assigned'] for m in members),
      f"{tp.get('total_members')}/{len(members)} {tp.get('total_assigned')}")

# ---------------------------------------------------------------------------
# Distribution endpoints (donut + priority) still live
# ---------------------------------------------------------------------------
sd = c.get('/api/v1/reports/status-distribution').get_json() or {}
pd = c.get('/api/v1/reports/priority-distribution').get_json() or {}
check('status-distribution shape', 'statuses' in sd and 'total' in sd
      and sd['total'] == sum(x['count'] for x in sd.get('statuses', [])),
      str((sd.get('total'), [x['count'] for x in sd.get('statuses', [])])))
check('priority-distribution shape', 'priorities' in pd and 'total' in pd
      and pd['total'] == sum(x['count'] for x in pd.get('priorities', [])),
      str((pd.get('total'), [x['count'] for x in pd.get('priorities', [])])))

# ---------------------------------------------------------------------------
# Filter scoping reaches the service layer
# ---------------------------------------------------------------------------
base_total = s.get('total_tasks')
proj = (c.get('/api/v1/reports/project-health').get_json() or {}).get('projects', [])
if proj:
    pid = proj[0]['id']
    rs = c.get(f'/api/v1/reports/summary?project_id={pid}').get_json() or {}
    check('summary ?project_id scopes totals', rs.get('total_tasks', -1) <= base_total,
          f'base={base_total} scoped={rs.get("total_tasks")}')
    rph = c.get(f'/api/v1/reports/project-health?project_id={pid}').get_json() or {}
    check('project-health ?project_id returns exactly that project',
          len(rph.get('projects', [])) == 1 and rph['projects'][0]['id'] == pid,
          str([p['id'] for p in rph.get('projects', [])]))
r_assignee = c.get('/api/v1/reports/summary?assignee_id=1')
check('summary ?assignee_id -> 200', r_assignee.status_code == 200,
      f'status={r_assignee.status_code}')
import datetime as _dt
r_dates = c.get(f'/api/v1/reports/summary?start_date=2020-01-01&end_date={_dt.date.today().isoformat()}')
check('summary date range -> 200', r_dates.status_code == 200,
      f'status={r_dates.status_code}')

# ---------------------------------------------------------------------------
# Health threshold unit check (reports-page rule only)
# ---------------------------------------------------------------------------
from app.services.report_service import _report_project_health

check('health: zero-task project -> Healthy', _report_project_health(0, 0, 0) == 'Healthy')
check('health: overdue>25% -> Critical', _report_project_health(10, 30, 80) == 'Critical')
check('health: overdue 10-25% -> Warning', _report_project_health(10, 15, 90) == 'Warning')
check('health: progress>60 no overdue -> Healthy', _report_project_health(10, 0, 65) == 'Healthy')
check('health: progress<=60 no overdue -> Warning', _report_project_health(10, 0, 40) == 'Warning')

# ---------------------------------------------------------------------------
# Reports page literals (keep required, drop removed)
# ---------------------------------------------------------------------------
r = c.get('/reports')
_rh = r.get_data(as_text=True)
check('Reports page renders', r.status_code == 200, f'status={r.status_code}')
required = ['id="kpiGrid"', 'Avg Velocity', 'Team Workload', 'Project Health',
            'Sprint Analytics', 'Overdue Analytics', 'overdueTotalChip', 'upcomingWrap',
            'Completed Work Over Time', 'chartCompleted', 'completedChip',
            'Team Performance', 'cardTeam', 'teamChip']
for lit in required:
    check(f'Reports keeps: {lit}', lit in _rh, '')
banned = ['id="filtersCard"', 'velocityChip', 'chartVelocity', 'Status Distribution',
          'chartStatus', 'Priority Distribution', 'chartPriority',
          'ReportApp.toggleFilters', 'ReportApp.exportCsv',
          "api('/api/v1/reports/velocity'", "api('/api/v1/reports/filters'"]
for lit in banned:
    check(f'Reports removed: {lit}', lit not in _rh, '')
newmarkers = ['reportFilters', 'chartTaskDist', 'chartWorkHours',
              'ReportApp.applyFilters', 'Top contributors']
for lit in newmarkers:
    check(f'Reports adds: {lit}', lit in _rh, '')

# ---------------------------------------------------------------------------
# Validation paths still behave
# ---------------------------------------------------------------------------
rv = c.get('/api/v1/reports/summary?project_id=99999')
check('unknown project -> 404', rv.status_code == 404, f'status={rv.status_code}')
rd = c.get('/api/v1/reports/drilldown?type=bogus')
check('invalid drilldown -> 400', rd.status_code == 400, f'status={rd.status_code}')

print('\n====================')
print(f'REPORTS DASHBOARD VERIFY: {len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    print('Failed:', FAIL)
    sys.exit(1)