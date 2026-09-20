"""End-to-end test of the refactored package using app.test_client()."""
import sys

sys.path.insert(0, r'C:\Users\SAFA FAYIS\sample_flaskapi_api')
from app import create_app

app = create_app()
c = app.test_client()

PASS = []
FAIL = []


def check(name, ok, extra=''):
    (PASS if ok else FAIL).append(name)
    status = 'PASS' if ok else 'FAIL'
    print(f'[{status}] {name}' + (f'  -> {extra}' if extra and not ok else ''))


# --- pages: login page loads (form fallback) ---
r = c.get('/login')
check('GET /login renders', r.status_code == 200 and 'login' in r.get_data(as_text=True).lower(),
      f'status={r.status_code}')

# --- JSON login via page route (hybrid kept) ---
r = c.post('/login', json={'email': 'alex@abc.io', 'password': 'password123'})
check('POST /login JSON ok', r.status_code == 200 and r.get_json().get('ok') is True,
      f'status={r.status_code} body={r.get_data(as_text=True)[:120]}')

# --- API auth endpoints ---
r = c.get('/api/v1/auth/me')
check('GET /api/v1/auth/me', r.status_code == 200 and r.get_json().get('email') == 'alex@abc.io')

# --- dashboard API ---
r = c.get('/api/v1/dashboard')
d = r.get_json()
check('GET /api/v1/dashboard', r.status_code == 200 and len(d.get('kpis')) == 4)

# --- issues ---
r = c.get('/api/v1/issues')
check('GET /api/v1/issues', r.status_code == 200 and isinstance(r.get_json(), list) and len(r.get_json()) >= 10)
issue = r.get_json()[0]
iid = issue['id']

r = c.get(f'/api/v1/issues/{iid}')
check('GET /api/v1/issues/{id}', r.status_code == 200 and r.get_json()['id'] == iid)

r = c.get(f'/api/v1/issues/{iid}/comments')
check('GET /api/v1/issues/{id}/comments', r.status_code == 200)

# --- projects ---
r = c.get('/api/v1/projects')
projects = r.get_json()
check('GET /api/v1/projects', r.status_code == 200 and len(projects) >= 4)
pid = projects[0]['id']

r = c.get(f'/api/v1/projects/{pid}/members')
check('GET /api/v1/projects/{id}/members', r.status_code == 200)

# --- sprints ---
r = c.get('/api/v1/sprints?project=ECOM')
check('GET /api/v1/sprints?project=ECOM', r.status_code == 200 and len(r.get_json()) >= 4,
      f'status={r.status_code} n={len(r.get_json()) if r.status_code==200 else "?"}')

# --- users ---
r = c.get('/api/v1/users')
check('GET /api/v1/users', r.status_code == 200 and len(r.get_json()) == 8)
r = c.get('/api/v1/team/roles')
check('GET /api/v1/team/roles', r.status_code == 200 and isinstance(r.get_json(), list))

# --- notifications ---
r = c.get('/api/v1/notifications')
check('GET /api/v1/notifications', r.status_code == 200 and 'notifications' in r.get_json())
r = c.get('/api/v1/notifications/unread-count')
check('GET /api/v1/notifications/unread-count', r.status_code == 200 and 'count' in r.get_json())

# --- reports ---
r = c.get('/api/v1/reports/summary')
check('GET /api/v1/reports/summary', r.status_code == 200 and 'total_tasks' in r.get_json())
r = c.get('/api/v1/reports/project-health')
check('GET /api/v1/reports/project-health', r.status_code == 200 and 'projects' in r.get_json())
r = c.get('/api/v1/reports/sprint-analytics')
check('GET /api/v1/reports/sprint-analytics', r.status_code == 200 and 'sprints' in r.get_json())
r = c.get('/api/v1/reports/velocity')
check('GET /api/v1/reports/velocity', r.status_code == 200)
r = c.get('/api/v1/reports/status-distribution')
check('GET /api/v1/reports/status-distribution', r.status_code == 200)
r = c.get('/api/v1/reports/priority-distribution')
check('GET /api/v1/reports/priority-distribution', r.status_code == 200)
r = c.get('/api/v1/reports/overdue')
check('GET /api/v1/reports/overdue', r.status_code == 200 and 'total_overdue' in r.get_json())
r = c.get('/api/v1/reports/completed-over-time')
check('GET /api/v1/reports/completed-over-time', r.status_code == 200)
r = c.get('/api/v1/reports/team-performance')
check('GET /api/v1/reports/team-performance', r.status_code == 200)
r = c.get('/api/v1/reports/filters')
check('GET /api/v1/reports/filters', r.status_code == 200 and 'projects' in r.get_json())
r = c.get('/api/v1/reports/drilldown?type=status&status=todo')
check('GET /api/v1/reports/drilldown?type=status', r.status_code == 200 and r.get_json()['type'] == 'status')

# validation paths
r = c.get('/api/v1/reports/drilldown?type=bogus')
check('drilldown invalid type -> 400', r.status_code == 400)
r = c.get('/api/v1/reports/summary?project_id=99999')
check('report unknown project -> 404', r.status_code == 404)

# --- ai ---
r = c.post('/api/v1/ai', json={'message': 'Which issues are overdue?'})
check('POST /api/v1/ai', r.status_code == 200 and 'response' in r.get_json())

# --- mutation tests (create + cleanup) ---
r = c.post('/api/v1/issues', json={
    'summary': 'Refactor smoke test task', 'project': 'ECOM',
    'issue_type': 'Task', 'priority': 'Medium', 'points': 3,
    'assignees': [1], 'status': 'todo',
})
body = r.get_json()
if r.status_code == 201:
    new_id = body['id']
    check('POST /api/v1/issues create', True)
    r = c.patch(f'/api/v1/issues/{new_id}', json={'priority': 'High'})
    check('PATCH /api/v1/issues priority', r.status_code == 200 and r.get_json()['priority'] == 'High')
    r = c.post(f'/api/v1/issues/{new_id}/move', json={'status': 'done'})
    _mv_now = c.get(f'/api/v1/issues/{new_id}').get_json()
    check('POST /api/v1/issues/{id}/move', r.status_code == 200 and _mv_now.get('status') == 'done',
          f'status={r.status_code} now={_mv_now.get("status")}')
    r = c.delete(f'/api/v1/issues/{new_id}')
    check('DELETE /api/v1/issues/{id}', r.status_code == 200)
else:
    check('POST /api/v1/issues create', False, str(body)[:160])

# comment add + delete
r = c.post('/api/v1/comments', json={'issue_id': issue['id'], 'body': 'smoke comment'})
if r.status_code == 201:
    cid = r.get_json()['id']
    check('POST /api/v1/issues/{id}/comments', True)
    r = c.delete(f'/api/v1/comments/{cid}')
    check('DELETE /api/v1/comments/{id}', r.status_code == 200)
else:
    check('POST /api/v1/issues/{id}/comments', False, f'status={r.status_code}')

# --- pages render ---
for path in ['/dashboard', '/projects', '/project', '/kanban', '/backlog', '/sprints',
             '/issue', '/my-work', '/team', '/people-hub', '/reports', '/calendar',
             '/notifications', '/ai-assistant']:
    r = c.get(path)
    check(f'GET {path} renders', r.status_code == 200,
          f'status={r.status_code}')

# reports & analytics cleanup: only KPI cards + Project Health + Sprint Analytics
r = c.get('/reports')
_rh = r.get_data(as_text=True)
check('Reports page renders', r.status_code == 200, f'status={r.status_code}')
check('Reports keeps KPI grid', 'id="kpiGrid"' in _rh and 'Avg Velocity' in _rh and 'Team Workload' in _rh,
      '')
check('Reports keeps Project Health + Sprint Analytics',
      'Project Health' in _rh and 'Sprint Analytics' in _rh, '')
check('Reports keeps Overdue Analytics',
      'Overdue Analytics' in _rh and 'overdueTotalChip' in _rh and 'upcomingWrap' in _rh, '')
check('Reports keeps Completed Work Over Time',
      'Completed Work Over Time' in _rh and 'chartCompleted' in _rh and 'completedChip' in _rh, '')
check('Reports keeps Team Performance',
      'Team Performance' in _rh and 'cardTeam' in _rh and 'teamChip' in _rh, '')
for _gone in ['id="filtersCard"', 'velocityChip', 'chartVelocity', 'Status Distribution',
              'chartStatus', 'Priority Distribution', 'chartPriority',
              'ReportApp.toggleFilters', 'ReportApp.exportCsv', "api('/api/v1/reports/velocity'",
              "api('/api/v1/reports/filters'"]:
    check(f'Reports removed: {_gone.lstrip(chr(34)).lstrip(chr(39))}',
          _gone not in _rh, '')

# --- swagger ---
r = c.get('/swagger.json')
spec = r.get_json()
api_paths = [p for p in spec['paths'] if p.startswith('/api/v1')]

check('GET /swagger.json', r.status_code == 200 and len(api_paths) == 46, f'api paths={len(api_paths)}')
# --- unauthorized API returns JSON 401 ---
c2 = app.test_client()
r = c2.get('/api/v1/notifications')
check('unauth API -> JSON 401', r.status_code == 401 and r.is_json)

# --- pro gate: lite user cannot create users ---
c3 = app.test_client()
r = c3.post('/api/v1/auth/login', json={'email': 'david@abc.io', 'password': 'password123'})
if r.status_code == 200:
    r = c3.post('/api/v1/users', json={'name': 'X', 'email': 'x@abc.io', 'password': 'xxxxxx', 'role': 'Dev'})
    check('non-pro create user -> 403', r.status_code == 403)
else:
    check('non-pro create user -> 403', False, f'login failed status={r.status_code}')

# =====================================================================
# Task Working Hours / Team Work Time — controlled scenario, cleaned up afterwards
# =====================================================================
# Working minutes live on the Task (Issue) row and are the single source of
# truth. Legacy Work Log / timer endpoints remain live for historical data
# but a Work Log can no longer influence these totals.
from datetime import datetime, timedelta

ALEX, DAVID = 1, 5
ECOM, BEA = 1, 6
created_log_ids = []
created_wh_issues = []


def wh_create(project_key, summary, status, working_minutes=None, assignee=1,
              parent_id=None, client=c):
    payload = {'summary': summary, 'project': project_key,
               'issue_type': 'Task', 'priority': 'Medium', 'points': 1,
               'assignees': [assignee], 'status': status}
    if working_minutes is not None:
        payload['working_minutes'] = working_minutes
    if parent_id:
        payload['parent_issue_id'] = parent_id
    r = client.post('/api/v1/issues', json=payload)
    if r.status_code == 201:
        created_wh_issues.append(r.get_json()['id'])
    return r


def wh_cleanup():
    for iid in list(created_wh_issues):
        try:
            r = c.delete(f'/api/v1/issues/{iid}', json={'confirm_subtasks': True})
            if r.status_code == 200:
                created_wh_issues.remove(iid)
        except Exception:
            pass


def wh_summary(project_id, client=c):
    return client.get(f'/api/v1/worklogs/summary?project_id={project_id}').get_json() or {}


def wh_member(summary_data, uid):
    for m in (summary_data or {}).get('members', []):
        if m.get('user_id') == uid:
            return m
    return None


def wl_post(project_id, work_date, start_time, end_time, worked_by=None, desc=None,
            issue_id='', client=c, extra=None):
    wd = work_date.isoformat() if hasattr(work_date, 'isoformat') else str(work_date)
    payload = {'project_id': project_id, 'work_date': wd,
               'start_time': start_time, 'end_time': end_time,
               'description': desc or '', 'issue_id': issue_id}
    if worked_by is not None:
        payload['worked_by_user_id'] = worked_by
    if extra:
        payload.update(extra)
    return client.post('/api/v1/worklogs', json=payload)


def wl_track(resp):
    b = resp.get_json() or {}
    if resp.status_code == 201:
        created_log_ids.append(b['work_log']['id'])
    return resp.status_code, b


def wl_cleanup():
    for log_id in list(created_log_ids):
        try:
            r = c.delete(f'/api/v1/worklogs/{log_id}')
            if r.status_code == 200:
                created_log_ids.remove(log_id)
        except Exception:
            pass


today = datetime.utcnow().date()
yesterday = today - timedelta(days=1)
two_days_ago = today - timedelta(days=2)

# --- Team Work Time summary shape (driven by task Working Hours) ---
wh_base0 = wh_summary(ECOM)
check('WH summary ok', wh_base0.get('ok') is True and len(wh_base0.get('members', [])) >= 5,
      f'ok={wh_base0.get("ok")} n={len(wh_base0.get("members", []))}')
check('WH summary audit context', wh_base0.get('current_user_id') == ALEX
      and isinstance(wh_base0.get('can_log_for_others'), bool), str(wh_base0)[:160])
check('WH zero-hour members shown',
      any((m or {}).get('total_minutes') == 0 for m in wh_base0.get('members', [])),
      'expected at least one member with no working hours')

ilist = c.get('/api/v1/issues?project=ECOM').get_json() or []
check('WH issue payload includes working_minutes/text',
      bool(ilist) and 'working_minutes' in ilist[0] and 'working_text' in ilist[0],
      str(ilist[0])[:160] if ilist else 'no issues')

# --- validation: Working Hours only meaningful when the task is Done ---
r = wh_create('ECOM', 'wh done no hours', 'done')
check('WH create done without hours accepted (null)', r.status_code == 201
      and r.get_json().get('working_minutes') is None,
      f'status={r.status_code} body={str(r.get_json())[:160]}')

r = wh_create('ECOM', 'wh done 03:45', 'done', working_minutes='03:45')
check('WH create done with 03:45 -> 225 / 3h 45m', r.status_code == 201
      and r.get_json().get('working_minutes') == 225
      and r.get_json().get('working_text') == '3h 45m',
      f'status={r.status_code} body={str(r.get_json())[:200]}')
done_issue_id = r.get_json().get('id') if r.status_code == 201 else None

r = wh_create('ECOM', 'wh done int minutes', 'done', working_minutes=90)
check('WH create done with int minutes -> 1h 30m', r.status_code == 201
      and r.get_json().get('working_text') == '1h 30m',
      f'status={r.status_code} body={str(r.get_json())[:160]}')

r = wh_create('ECOM', 'wh todo with hours', 'todo', working_minutes=60)
check('WH create non-done with hours -> 400', r.status_code == 400
      and 'Done' in r.get_json().get('error', ''),
      f'status={r.status_code} err={r.get_json().get("error")}')

r = wh_create('ECOM', 'wh bad format', 'done', working_minutes='abc')
check('WH create bad hours format -> 400', r.status_code == 400, f'status={r.status_code}')
r = wh_create('ECOM', 'wh zero hours', 'done', working_minutes='00:00')
check('WH create zero hours -> 400', r.status_code == 400, f'status={r.status_code}')

# --- update rules ---
if done_issue_id:
    pr = c.patch(f'/api/v1/issues/{done_issue_id}', json={'status': 'backlog'})
    check('WH reopen via patch clears hours', pr.status_code == 200
          and pr.get_json().get('working_minutes') is None,
          f'status={pr.status_code} body={str(pr.get_json())[:160]}')
rt_ = wh_create('ECOM', 'wh patch done->reopen', 'todo')
if rt_.status_code == 201:
    ri = rt_.get_json()['id']
    p1 = c.patch(f'/api/v1/issues/{ri}', json={'status': 'done', 'working_minutes': '02:00'})
    check('WH patch to done with hours ok -> 2h 00m', p1.status_code == 200
          and p1.get_json().get('working_minutes') == 120
          and p1.get_json().get('working_text') == '2h 00m',
          f'status={p1.status_code} body={str(p1.get_json())[:200]}')
    p2 = c.patch(f'/api/v1/issues/{ri}', json={'status': 'done', 'working_minutes': 'bad'})
    check('WH patch bad hours -> 400', p2.status_code == 400, f'status={p2.status_code}')
    p3 = c.patch(f'/api/v1/issues/{ri}', json={'status': 'todo'})
    check('WH patch reopen clears hours', p3.status_code == 200
          and p3.get_json().get('working_minutes') is None
          and p3.get_json().get('working_text') is None,
          f'status={p3.status_code} body={str(p3.get_json())[:160]}')
    c.delete(f'/api/v1/issues/{ri}')
    if ri in created_wh_issues:
        created_wh_issues.remove(ri)

rm_ = wh_create('ECOM', 'wh move flow', 'todo')
if rm_.status_code == 201:
    rmid = rm_.get_json()['id']
    mv = c.post(f'/api/v1/issues/{rmid}/move', json={'status': 'done'})
    cur = c.get(f'/api/v1/issues/{rmid}').get_json()
    check('WH move to done works without hours', mv.status_code == 200
          and cur.get('status') == 'done' and cur.get('working_minutes') is None,
          f'status={mv.status_code} now={cur.get("status")}')
    mv2 = c.post(f'/api/v1/issues/{rmid}/move', json={'status': 'backlog'})
    cur2 = c.get(f'/api/v1/issues/{rmid}').get_json()
    check('WH move reopen leaves hours null', mv2.status_code == 200
          and cur2.get('working_minutes') is None, f'status={mv2.status_code}')

# baseline captured AFTER the rule tests (the done-with-hours scratch issue
# 'wh done int minutes' still counts toward the totals below)
mid_wh = wh_summary(ECOM)
mid_alex_total = (wh_member(mid_wh, ALEX) or {}).get('total_minutes', 0)
mid_alex_today = (wh_member(mid_wh, ALEX) or {}).get('today_minutes', 0)
mid_david_total = (wh_member(mid_wh, DAVID) or {}).get('total_minutes', 0)
mid_proj_total = (mid_wh.get('totals') or {}).get('total_minutes', 0)

# --- Team Work Time aggregated from task Working Hours (leaf rule) ---
r = wh_create('ECOM', 'wh works alex 90', 'done', working_minutes=90, assignee=ALEX)
check('WH done leaf alex created', r.status_code == 201, f'status={r.status_code}')
r = wh_create('ECOM', 'wh works david 30', 'done', working_minutes='00:30', assignee=DAVID)
check('WH done leaf david created', r.status_code == 201, f'status={r.status_code}')

rp = wh_create('ECOM', 'wh parent 60', 'done', working_minutes=60, assignee=ALEX)
parent_id = rp.get_json().get('id') if rp.status_code == 201 else None
rch = wh_create('ECOM', 'wh child 45', 'done', working_minutes=45, assignee=ALEX,
                parent_id=parent_id)
check('WH child of done parent created', rch.status_code == 201
      and rch.get_json().get('parent_issue_id') == parent_id,
      f'status={rch.status_code} body={str(rch.get_json())[:180]}')

s_l = wh_summary(ECOM)
am = wh_member(s_l, ALEX)
dm = wh_member(s_l, DAVID)
tl = s_l.get('totals') or {}
check('WH leaf rule: parent 60 excluded (child 45 + leaf 90 count)',
      am and am['total_minutes'] == mid_alex_total + 90 + 45,
      f"alex_total={am and am['total_minutes']} want={mid_alex_total + 135}")
check('WH david total +30', dm and dm['total_minutes'] == mid_david_total + 30,
      f"david_total={dm and dm['total_minutes']} want={mid_david_total + 30}")
check('WH project total tracks leaves only', tl.get('total_minutes') == mid_proj_total + 165,
      f"proj_total={tl.get('total_minutes')} want={mid_proj_total + 165}")
check('WH today counts tasks completed today',
      am and am['today_minutes'] == mid_alex_today + 90 + 45,
      f"alex_today={am and am['today_minutes']} want={mid_alex_today + 135}")

# a legacy Work Log must NOT move the Team Work Time totals
st0, _ = wl_track(wl_post(ECOM, today, '09:00', '10:00', worked_by=ALEX, desc='legacy probe'))
check('WH legacy work log created (endpoint alive)', st0 == 201, f'status={st0}')
s_after_log = wh_summary(ECOM)
check('WH work log does not change totals',
      (wh_member(s_after_log, ALEX) or {}).get('total_minutes')
      == (wh_member(s_l, ALEX) or {}).get('total_minutes'),
      f"before={(wh_member(s_l, ALEX) or {}).get('total_minutes')} "
      f"after={(wh_member(s_after_log, ALEX) or {}).get('total_minutes')}")

# project isolation: BEA hours land only on BEA
rb_ = wh_create('BEA', 'wh bea alex 30', 'done', working_minutes=30, assignee=ALEX)
check('WH create BEA done task', rb_.status_code == 201, f'status={rb_.status_code}')
s_ecm = wh_summary(ECOM)
s_bea = wh_summary(BEA)
check('WH isolation ECOM unchanged',
      (wh_member(s_ecm, ALEX) or {}).get('total_minutes')
      == (wh_member(s_after_log, ALEX) or {}).get('total_minutes'))
check('WH isolation BEA counts 30',
      (wh_member(s_bea, ALEX) or {}).get('total_minutes', 0) >= 30,
      f"bea={(wh_member(s_bea, ALEX) or {}).get('total_minutes')}")

# --- legacy Work Log endpoint rules (endpoints still live) ---
def wl_case(start, end, extra=None):
    st_, b_ = wl_track(wl_post(ECOM, today, start, end, worked_by=ALEX,
                               desc='time case', extra=extra))
    if st_ == 201:
        return b_['work_log']['duration_minutes']
    return None

check('WL 10:00->11:00 = 1h', wl_case('10:00', '11:00') == 60)
check('WL 10:00->12:30 = 2h30m', wl_case('10:00', '12:30') == 150)
check('WL 14:15->16:45 = 2h30m', wl_case('14:15', '16:45') == 150)
check('WL 09:30->10:00 = 30m', wl_case('09:30', '10:00') == 30)

# start/end validation
r = wl_post(ECOM, today, '10:00', '10:00', worked_by=ALEX)
b = r.get_json() or {}
check('WL same start/end rejected', r.status_code == 400 and 'greater than zero' in b.get('error', ''),
      f'status={r.status_code} err={b.get("error")}')
r = wl_post(ECOM, today, '14:00', '12:00', worked_by=ALEX)
b = r.get_json() or {}
check('WL end-before-start rejected', r.status_code == 400 and 'after start time' in b.get('error', ''),
      f'status={r.status_code} err={b.get("error")}')
r = wl_post(ECOM, today, None, '12:00', worked_by=ALEX)
check('WL missing start -> 400', r.status_code == 400, f'status={r.status_code}')
r = wl_post(ECOM, today, '10:00', None, worked_by=ALEX)
check('WL missing end -> 400', r.status_code == 400, f'status={r.status_code}')
r = wl_post(ECOM, today, '25:00', '26:00', worked_by=ALEX)
check('WL invalid time -> 400', r.status_code == 400, f'status={r.status_code}')
r = wl_post(ECOM, 'not-a-date', '09:00', '10:00', worked_by=ALEX)
check('WL invalid date -> 400', r.status_code == 400, f'status={r.status_code}')
_itemps = c.get('/api/v1/issues?project=BANK').get_json()
if isinstance(_itemps, list) and _itemps:
    r = wl_post(ECOM, today, '09:00', '10:00', worked_by=ALEX, issue_id=_itemps[0]['id'])
    check('WL cross-project issue -> 400', r.status_code == 400, f'status={r.status_code}')
else:
    check('WL cross-project issue -> 400', False, 'no BANK issue found')

# backend is the source of truth: a forged duration is ignored and recomputed
r = wl_post(ECOM, today, '10:00', '11:00', worked_by=ALEX, desc='forged duration',
            extra={'duration': '00:10', 'duration_minutes': 999})
b = r.get_json() or {}
check('WL forged duration ignored (60 computed)', r.status_code == 201
      and b.get('work_log', {}).get('duration_minutes') == 60,
      f'status={r.status_code} body={str(b)[:180]}')
if r.status_code == 201:
    created_log_ids.append(b['work_log']['id']) if b['work_log']['id'] not in created_log_ids else None

# 12-hour input is accepted and normalized to 24h storage
r = wl_post(ECOM, today, '10:00 AM', '12:30 PM', worked_by=ALEX, desc='12h case')
b = r.get_json() or {}
check('WL 12-hour times accepted', r.status_code == 201
      and b.get('work_log', {}).get('start_time') == '10:00'
      and b.get('work_log', {}).get('end_time') == '12:30'
      and b.get('work_log', {}).get('duration_minutes') == 150,
      f'status={r.status_code} body={str(b)[:180]}')
if r.status_code == 201 and b['work_log']['id'] not in created_log_ids:
    created_log_ids.append(b['work_log']['id'])

# duplicate POST creates separate rows (UI disable protects; backend persists each)
st1, b1 = wl_track(wl_post(ECOM, yesterday, '09:00', '10:00', worked_by=ALEX, desc='dup'))
st2, b2 = wl_track(wl_post(ECOM, yesterday, '09:00', '10:00', worked_by=ALEX, desc='dup'))
check('WL duplicate saves are separate rows', st1 == 201 and st2 == 201 and b1['work_log']['id'] != b2['work_log']['id'])

# non-manager (David) cannot log for / view another member
dc = app.test_client()
dl = dc.post('/api/v1/auth/login', json={'email': 'david@abc.io', 'password': 'password123'})
if dl.status_code == 200:
    r = wl_post(ECOM, today, '09:00', '09:30', worked_by=ALEX, client=dc)
    check('WL non-manager log-for-other -> 403', r.status_code == 403, f'status={r.status_code}')
    r = dc.get(f'/api/v1/worklogs?project_id={ECOM}&user_id={ALEX}')
    check('WL non-manager view other member -> 403', r.status_code == 403, f'status={r.status_code}')
    r = dc.get(f'/api/v1/worklogs?project_id={ECOM}')
    check('WL member lists own logs only', r.status_code == 200 and all(
        w.get('worked_by_user_id') == DAVID for w in (r.get_json() or {}).get('work_logs', [])),
        f'status={r.status_code}')
else:
    check('WL non-manager flows', False, f'david login {dl.status_code}')

# non-member cannot access project time data
sc2 = app.test_client()
sr = sc2.post('/api/v1/auth/login', json={'email': 'sarah@abc.io', 'password': 'password123'})
if sr.status_code == 200:
    r = sc2.get('/api/v1/worklogs/summary?project_id=2')
    check('WL non-member summary -> 403', r.status_code == 403, f'status={r.status_code}')
    r = sc2.post('/api/v1/worklogs', json={'project_id': 2, 'work_date': today.isoformat(),
                                           'start_time': '09:00', 'end_time': '10:00'})
    check('WL non-member create -> 403', r.status_code == 403, f'status={r.status_code}')
else:
    check('WL non-member flows', False, f'sarah login {sr.status_code}')

# issue reassignment (section 40): historical work stays with the worker
ric = c.post('/api/v1/issues', json={'summary': 'reassign test', 'project': 'ECOM',
                                     'issue_type': 'Task', 'priority': 'Medium',
                                     'points': 1, 'assignees': [1], 'status': 'todo'})
if ric.status_code == 201:
    riid = ric.get_json()['id']
    st, b = wl_track(wl_post(ECOM, today, '10:00', '12:00', worked_by=ALEX,
                             desc='reassign test', issue_id=riid))
    if st == 201:
        from app.models import Issue as _R_Issue
        from app.extensions import db as _R_db
        with app.app_context():
            _iss = _R_Issue.query.get(riid)
            _iss.assignee_id = DAVID
            _R_db.session.commit()
        rl = c.get(f'/api/v1/worklogs?project_id={ECOM}&user_id={ALEX}')
        still_alex = any(w.get('id') == b['work_log']['id'] and w.get('worked_by_user_id') == ALEX
                         for w in (rl.get_json() or {}).get('work_logs', []))
        check('WL reassignment keeps work with original worker', still_alex)
    else:
        check('WL reassignment keeps work with original worker', False, str(b)[:160])
    c.delete(f'/api/v1/issues/{riid}')
else:
    check('WL reassignment keeps work with original worker', False, f'create {ric.status_code}')

# scratch cleanup: totals return to the pre-scenario baseline
wh_cleanup()
wl_cleanup()
s_final = wh_summary(ECOM)
check('WH cleanup restores baseline totals',
      (wh_member(s_final, ALEX) or {}).get('total_minutes')
      == (wh_member(wh_base0, ALEX) or {}).get('total_minutes')
      and (wh_member(s_final, DAVID) or {}).get('total_minutes')
      == (wh_member(wh_base0, DAVID) or {}).get('total_minutes'),
      f"alex={(wh_member(s_final, ALEX) or {}).get('total_minutes')} "
      f"want={(wh_member(wh_base0, ALEX) or {}).get('total_minutes')}")

# =====================================================================
# Automatic Work Timer — Start Work / Stop Work
# =====================================================================
import threading as _th


def tm_start(project_id, issue_id, client=c, extra=None):
    payload = {'project_id': project_id, 'issue_id': issue_id}
    if extra:
        payload.update(extra)
    return client.post('/api/v1/worklogs/timer/start', json=payload)


def tm_stop(client=c, issue_id=None):
    payload = {}
    if issue_id is not None:
        payload['issue_id'] = issue_id
    return client.post('/api/v1/worklogs/timer/stop', json=payload)


def tm_active(client=c, project_id=None):
    url = '/api/v1/worklogs/timer/active'
    if project_id is not None:
        url += f'?project_id={project_id}'
    return client.get(url).get_json() or {}


created_timer_ids = []
now = datetime.utcnow()

ec_issues = c.get('/api/v1/issues?project=ECOM').get_json() or []
ec_issue = ec_issues[0]['id'] if ec_issues else None
ec_issue2 = ec_issues[1]['id'] if len(ec_issues) > 1 else None
bank_issue = (c.get('/api/v1/issues?project=BANK').get_json() or [{}])[0].get('id') or None

tmp_timer_issues = []


def _mk_timer_issue(project_key):
    r = c.post('/api/v1/issues', json={'summary': 'timer auto test', 'project': project_key,
                                       'issue_type': 'Task', 'priority': 'Medium',
                                       'points': 1, 'assignees': [1], 'status': 'todo'})
    if r.status_code == 201:
        iid = r.get_json()['id']
        tmp_timer_issues.append(iid)
        return iid
    return None


def _tm_backdate(timer_id, delta):
    import psycopg2 as _pg2
    _conn = _pg2.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
    _cur = _conn.cursor()
    _cur.execute('UPDATE work_timers SET started_at = %s WHERE id = %s',
                 (datetime.utcnow() - delta, timer_id))
    _conn.commit()
    _conn.close()


def _tm_row(timer_id):
    import psycopg2 as _pg2
    _conn = _pg2.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
    _cur = _conn.cursor()
    _cur.execute('SELECT user_id, project_id, issue_id, stopped_at, work_log_id '
                 'FROM work_timers WHERE id = %s', (timer_id,))
    row = _cur.fetchone()
    _conn.close()
    return row


def _wl_gone(log_id):
    import psycopg2 as _pg2
    _conn = _pg2.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
    _cur = _conn.cursor()
    _cur.execute('SELECT count(*) FROM work_logs WHERE id = %s', (log_id,))
    n = _cur.fetchone()[0]
    _conn.close()
    return n


def tm_cleanup():
    from app.models import WorkTimer as _TM
    from app.extensions import db as _DB2
    with app.app_context():
        for tid in list(created_timer_ids):
            row = _TM.query.get(tid)
            if row is None:
                created_timer_ids.remove(tid)
                continue
            if row.stopped_at is None:
                row.stopped_at = datetime.utcnow()
            _DB2.session.delete(row)
        _DB2.session.commit()


# Team Work Time totals are now driven solely by task Working Hours
# (legacy timer/Work Log rows do not feed the summary), so there is nothing
# to baseline here from the summary.

# ---- start ----
if ec_issue is None:
    check('TM start work (201)', False, 'no ECOM issue found')
tmr = tm_start(ECOM, ec_issue)
tb = tmr.get_json() or {}
check('TM start work (201)', tmr.status_code == 201 and tb.get('timer') and tb['timer']['issue_id'] == ec_issue,
      f'status={tmr.status_code} body={str(tb)[:160]}')
if tmr.status_code == 201:
    created_timer_ids.append(tb['timer']['id'])
    check('TM server timestamps present', bool(tb['timer'].get('started_at')) and bool(tb['timer'].get('server_now')),
          str(tb['timer'])[:160])
    check('TM timer owned by actor (forged user_id ignored)',
          tb['timer'].get('user_id') == ALEX, str(tb['timer'])[:160])
    # persisted in PostgreSQL as an ACTIVE row
    row = _tm_row(tb['timer']['id'])
    check('TM active timer stored in PostgreSQL',
          row and row[0] == ALEX and row[1] == ECOM and row[2] == ec_issue and row[3] is None,
          str(row))

# ---- active endpoint ----
a = tm_active()
check('TM active endpoint returns timer', a.get('active') is True
      and created_timer_ids and a['timer']['id'] == created_timer_ids[0], str(a)[:160])
check('TM active includes elapsed seconds', isinstance(a.get('timer', {}).get('elapsed_seconds'), int),
      str(a)[:160])

# ---- duplicate / one-active protection ----
r = tm_start(ECOM, ec_issue)
check('TM duplicate start rejected (409)',
      r.status_code == 409 and 'active work timer for' in (r.get_json() or {}).get('error', ''),
      f'status={r.status_code} err={(r.get_json() or {}).get("error")}')
if ec_issue2:
    r = tm_start(ECOM, ec_issue2)
    check('TM second issue start rejected (409)',
          r.status_code == 409 and 'active work timer for' in (r.get_json() or {}).get('error', ''),
          f'status={r.status_code}')
else:
    check('TM second issue start rejected (409)', False, 'no second ECOM issue')
if bank_issue:
    r = tm_start(ECOM, bank_issue)
    check('TM cross-project issue -> 400',
          r.status_code == 400 and 'does not belong' in (r.get_json() or {}).get('error', ''),
          f'status={r.status_code} err={(r.get_json() or {}).get("error")}')
else:
    check('TM cross-project issue -> 400', False, 'no BANK issue')
bea_probe = _mk_timer_issue('BEA')
check('TM BEA issue setup', bea_probe is not None, 'bea issue creation failed')
# one active timer per user ACROSS projects
r = tm_start(6, bea_probe)
check('TM one-active across projects -> 409',
      r.status_code == 409 and 'active work timer for' in (r.get_json() or {}).get('error', ''),
      f'status={r.status_code} err={(r.get_json() or {}).get("error")}')

# ---- refresh / navigation / logout persistence ----
c2 = app.test_client()
lr2 = c2.post('/api/v1/auth/login', json={'email': 'alex@abc.io', 'password': 'password123'})
if lr2.status_code == 200:
    a2 = tm_active(client=c2)
    check('TM timer persists across refresh/login', a2.get('active') is True
          and created_timer_ids and a2['timer']['id'] == created_timer_ids[0], str(a2)[:160])
    for url in ['/dashboard', '/projects', '/kanban?project=ECOM', '/backlog?project=ECOM',
                '/sprints?project=ECOM', '/my-work', '/project?project=1', f'/issue/{ec_issue}']:
        rr = c2.get(url)
        if rr.status_code != 200:
            check(f'TM page renders while timer active ({url})', False, f'status={rr.status_code}')
    pg = c2.get(f'/issue/{ec_issue}')
    check('TM issue page renders with Working Hours card', pg.status_code == 200
          and 'Working Hours' in pg.get_data(as_text=True), f'status={pg.status_code}')
else:
    check('TM refresh persistence', False, f'login {lr2.status_code}')
# logout does NOT stop the timer; the next login still sees it
c3 = app.test_client()
if c3.post('/api/v1/auth/login', json={'email': 'alex@abc.io', 'password': 'password123'}).status_code == 200:
    c3.get('/api/v1/auth/logout')
    c3.post('/api/v1/auth/login', json={'email': 'alex@abc.io', 'password': 'password123'})
    a3 = tm_active(client=c3)
    check('TM logout leaves timer active', a3.get('active') is True
          and created_timer_ids and a3['timer']['id'] == created_timer_ids[0],
          f'active={a3.get("active")} ids={created_timer_ids}')

# ---- someone else cannot see/stop it ----
if dl.status_code == 200:
    ad = tm_active(client=dc)
    rd = tm_stop(client=dc, issue_id=ec_issue)
    check('TM other user sees no timer', ad.get('active') is False, str(ad)[:120])
    check('TM other user cannot stop timer -> 409', rd.status_code == 409, f'status={rd.status_code}')
else:
    check('TM cross-user rules', False, 'david login')

# ---- duration correctness (server timestamps are authoritative) ----
tid = created_timer_ids[0]
# zero/negative duration rejected: future started_at
_tm_backdate(tid, timedelta(minutes=-5))
rz = tm_stop(issue_id=ec_issue)
check('TM zero/negative duration rejected (409)',
      rz.status_code == 409 and 'greater than zero' in (rz.get_json() or {}).get('error', ''),
      f'status={rz.status_code} err={(rz.get_json() or {}).get("error")}')
a = tm_active()
check('TM timer still active after rejected stop', a.get('active') is True, str(a)[:120])
# backdate 2h10m -> stop -> duration must be exactly 130 minutes
_tm_backdate(tid, timedelta(hours=2, minutes=10))
rs = tm_stop(issue_id=ec_issue)
sb = rs.get_json() or {}
check('TM stop work (201)', rs.status_code == 201 and sb.get('work_log', {}).get('duration_minutes') == 130,
      f'status={rs.status_code} body={str(sb)[:180]}')
if rs.status_code == 201:
    wl = sb['work_log']
    created_log_ids.append(wl['id'])
    check('TM auto log worked_by==logged_by==actor',
          wl.get('worked_by_user_id') == ALEX and wl.get('logged_by_user_id') == ALEX, str(wl)[:160])
    check('TM auto log project/issue correct', wl.get('project_id') == ECOM and wl.get('issue_id') == ec_issue,
          str(wl)[:160])
    check('TM auto log date is UTC today', wl.get('work_date') == today.isoformat(), str(wl)[:160])
    row = _tm_row(tid)
    check('TM timer closed in PostgreSQL', row and row[3] is not None and row[4] == wl['id'], str(row))
    n = _wl_gone(wl['id'])
    check('TM one Work Log persisted', n == 1, f'count={n}')
    s2 = wh_summary(ECOM)
    check('TM timer log does not move Working Hours totals',
          (wh_member(s2, ALEX) or {}).get('total_minutes')
          == (wh_member(wh_base0, ALEX) or {}).get('total_minutes'),
          f"now={(wh_member(s2, ALEX) or {}).get('total_minutes')} "
          f"want={(wh_member(wh_base0, ALEX) or {}).get('total_minutes')}")

# active closed: duplicate stop must not create a second log
before_count = 0
import psycopg2 as _pg2b
_conn = _pg2b.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
_cur = _conn.cursor()
_cur.execute('SELECT count(*) FROM work_logs WHERE worked_by_user_id=%s AND project_id=%s', (ALEX, ECOM))
before_count = _cur.fetchone()[0]
_conn.close()
rd2 = tm_stop(issue_id=ec_issue)
check('TM duplicate stop -> 409 no duplicate log',
      rd2.status_code == 409 and 'No active work timer' in (rd2.get_json() or {}).get('error', ''),
      f'status={rd2.status_code} err={(rd2.get_json() or {}).get("error")}')
a = tm_active()
check('TM active endpoint empty after stop', a.get('active') is False, str(a)[:120])
import psycopg2 as _pg2c
_conn = _pg2c.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
_cur = _conn.cursor()
_cur.execute('SELECT count(*) FROM work_logs WHERE worked_by_user_id=%s AND project_id=%s', (ALEX, ECOM))
after_count = _cur.fetchone()[0]
_conn.close()
check('TM duplicate stop created no extra Work Log', after_count == before_count,
      f"before={before_count} after={after_count}")

# ---- forged worked_by on a fresh timer is ignored ----
rf = tm_start(ECOM, ec_issue, extra={'worked_by_user_id': DAVID, 'user_id': DAVID})
fb = rf.get_json() or {}
check('TM forged worked_by returns actor-owned timer', rf.status_code == 201
      and fb.get('timer', {}).get('user_id') == ALEX, f'status={rf.status_code} body={str(fb)[:160]}')
if rf.status_code == 201:
    created_timer_ids.append(fb['timer']['id'])
    _tm_backdate(fb['timer']['id'], timedelta(minutes=20))
    rf_stop = tm_stop()
    if rf_stop.status_code == 201:
        created_log_ids.append(rf_stop.get_json()['work_log']['id'])

# ---- isolation: BEA timer is project-scoped; nothing else moves ----
if bea_probe:
    rb = tm_start(6, bea_probe)
    bb = rb.get_json() or {}
    check('TM start on BEA (201)', rb.status_code == 201 and bb.get('timer', {}).get('project_id') == 6,
          f'status={rb.status_code} body={str(bb)[:160]}')
    if rb.status_code == 201:
        created_timer_ids.append(bb['timer']['id'])
        _tm_backdate(bb['timer']['id'], timedelta(hours=1))
        r_bs = tm_stop()
        if r_bs.status_code == 201:
            created_log_ids.append(r_bs.get_json()['work_log']['id'])
            wlb = r_bs.get_json()['work_log']
            check('TM BEA stop log scoped to project 6', wlb.get('project_id') == 6,
                  str(wlb)[:160])
        else:
            check('TM BEA stop (201)', False, f'status={r_bs.status_code}')
else:
    check('TM start on BEA (201)', False, 'bea issue missing')

# ---- reassignment while timer active: timer + log stay with the worker ----
if ec_issue2:
    rr = tm_start(ECOM, ec_issue2)
    rr_b = rr.get_json() or {}
    check('TM start before reassignment (201)', rr.status_code == 201, f'status={rr.status_code}')
    if rr.status_code == 201:
        created_timer_ids.append(rr_b['timer']['id'])
        from app.models import Issue as _TM_Issue
        from app.extensions import db as _TM_db
        with app.app_context():
            _iss2 = _TM_Issue.query.get(ec_issue2)
            _iss2.assignee_id = DAVID
            _TM_db.session.commit()
        row = _tm_row(rr_b['timer']['id'])
        check('TM reassignment does not transfer active timer',
              row and row[0] == ALEX and row[2] == ec_issue2, str(row))
        _tm_backdate(rr_b['timer']['id'], timedelta(minutes=45))
        r_st = tm_stop()
        if r_st.status_code == 201:
            created_log_ids.append(r_st.get_json()['work_log']['id'])
            check('TM reassigned-issue log stays with worker',
                  r_st.get_json()['work_log']['worked_by_user_id'] == ALEX,
                  str(r_st.get_json()['work_log'])[:160])

# ---- non-member rules ----
sc2 = app.test_client()
sl_ = sc2.post('/api/v1/auth/login', json={'email': 'sarah@abc.io', 'password': 'password123'})
if sl_.status_code == 200:
    rn = tm_start(2, bank_issue, client=sc2) if bank_issue else None
    check('TM non-member start -> 403', rn is not None and rn.status_code == 403,
          f'status={(rn.status_code if rn else None)} err={(rn.get_json() or {}).get("error") if rn else ""}')
else:
    check('TM non-member start -> 403', False, f'sarah login {sl_.status_code}')

# ---- concurrent Start requests: exactly one active timer ----
race_codes = []


def _race_start():
    _cl = app.test_client()
    _cl.post('/api/v1/auth/login', json={'email': 'alex@abc.io', 'password': 'password123'})
    _r = _cl.post('/api/v1/worklogs/timer/start', json={'project_id': ECOM, 'issue_id': ec_issue})
    race_codes.append(_r.status_code)


_threads = [_th.Thread(target=_race_start) for _ in range(2)]
for _t in _threads:
    _t.start()
for _t in _threads:
    _t.join()
check('TM concurrent starts -> exactly one active', sorted(race_codes) == [201, 409], f'codes={race_codes}')
# stop + cleanup the race winner if any 201
if 201 in race_codes:
    # find and stop whatever active timer remains
    ar = tm_active()
    if ar.get('active'):
        st = tm_stop()
        if st.status_code == 201:
            created_log_ids.append(st.get_json()['work_log']['id'])
            created_timer_ids.append(ar['timer']['id'])


# ---- timers cleanup (before work-log cleanup so FK stays valid) ----
tm_cleanup()

# remove all timer-created work logs and temp issues
wl_cleanup()
for tii in tmp_timer_issues:
    try:
        c.delete(f'/api/v1/issues/{tii}')
    except Exception:
        pass
s_base2 = wh_summary(ECOM)
check('TM cleanup restores Working Hours baseline',
      (wh_member(s_base2, ALEX) or {}).get('total_minutes')
      == (wh_member(wh_base0, ALEX) or {}).get('total_minutes')
      and (wh_member(s_base2, DAVID) or {}).get('total_minutes')
      == (wh_member(wh_base0, DAVID) or {}).get('total_minutes'),
      f"alex={(wh_member(s_base2, ALEX) or {}).get('total_minutes')} "
      f"want={(wh_member(wh_base0, ALEX) or {}).get('total_minutes')}")
# no active timers left behind
left = 0
import psycopg2 as _pg2e
_conn = _pg2e.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
_cur = _conn.cursor()
_cur.execute('SELECT count(*) FROM work_timers WHERE stopped_at IS NULL')
left = _cur.fetchone()[0]
_conn.close()
check('TM no active timers left behind', left == 0, f'active={left}')

# =====================================================================
# Project Progress — single backend rule (done/total), shared everywhere
# =====================================================================
import psycopg2 as _pg3


def pp_dash():
    d = c.get('/api/v1/dashboard').get_json() or {}
    return {p['id']: p for p in d.get('projects', [])}


def pp_issue(project_key, summary, status='backlog', extra=None):
    payload = {'summary': summary, 'project': project_key,
               'issue_type': 'Task', 'status': status}
    if extra:
        payload.update(extra)
    return c.post('/api/v1/issues', json=payload)


def pp_move(issue_id, status):
    return c.post(f'/api/v1/issues/{issue_id}/move', json={'status': status})


# zero-issue project stays 0 (never NaN / never 100)
bea_row = pp_dash().get(BEA, {})
check('PP zero-issue project -> 0%', bea_row.get('progress_percentage') == 0
      and bea_row.get('total_issues') == 0 and bea_row.get('done_issues') == 0,
      str(bea_row)[:140])

ecm_before = (pp_dash().get(ECOM) or {}).get('progress_percentage')

rp = c.post('/api/v1/projects', json={
    'name': 'Progress Scratch', 'start_date': '2025-01-01',
    'target_date': '2025-12-31', 'manager_id': 1, 'assignees': [1],
})
pb = rp.get_json() or {}
scratch = pb.get('id')
scratch_key = pb.get('key')
if rp.status_code == 201 and scratch:
    check('PP create scratch project', True)
    check('PP scratch created at 0%', pb.get('progress_percentage') == 0
          and pb.get('progress') == 0 and pb.get('total_issues') == 0
          and pb.get('done_issues') == 0, str(pb)[:180])

    st = ['done', 'todo', 'backlog', 'backlog', 'in_review', 'in_progress',
          'backlog', 'todo', 'backlog', 'done', 'in_progress']
    ids = []
    created_ok = True
    for i, status in enumerate(st):
        r = pp_issue(scratch_key, f'PP{i + 1} {status}', status=status)
        ib = r.get_json() or {}
        if r.status_code == 201:
            ids.append(ib['id'])
        else:
            created_ok = False
            break
    check('PP create 11 mixed issues', created_ok and len(ids) == 11, f'n={len(ids)}')

    def pp_val():
        row = pp_dash().get(scratch, {})
        return row.get('progress_percentage'), row.get('total_issues'), row.get('done_issues')

    pct, tot, don = pp_val()
    check('PP 2/11 -> 18% (backlog/todo/in_review all count)',
          (pct, tot, don) == (18, 11, 2), f'{pct}% {don}/{tot}')
    for i in (ids[1], ids[2], ids[3]):
        pp_move(i, 'done')
    pct, tot, don = pp_val()
    check('PP 5/11 -> 45% (rounds down)',
          (pct, tot, don) == (45, 11, 5), f'{pct}% {don}/{tot}')
    pp_move(ids[4], 'done')
    pct, tot, don = pp_val()
    check('PP 6/11 -> 55% (rounds up)',
          (pct, tot, don) == (55, 11, 6), f'{pct}% {don}/{tot}')
    for i in (ids[5], ids[6], ids[7], ids[8], ids[10]):
        pp_move(i, 'done')
    pct, tot, don = pp_val()
    check('PP 11/11 -> 100%', (pct, tot, don) == (100, 11, 11), f'{pct}% {don}/{tot}')

    pp_move(ids[0], 'in_progress')
    pct, tot, don = pp_val()
    check('PP move out of done -> 91%', (pct, tot, don) == (91, 11, 10), f'{pct}% {don}/{tot}')
    pp_move(ids[0], 'done')
    pct, tot, don = pp_val()
    check('PP move back into done -> 100%', (pct, tot, don) == (100, 11, 11), f'{pct}% {don}/{tot}')

    r = pp_issue(scratch_key, 'PP unassigned backlog', status='backlog')
    if r.status_code == 201:
        ids.append(r.get_json()['id'])
        pct, tot, don = pp_val()
        check('PP unassigned backlog counts -> 92% (11/12)',
              r.get_json().get('assignee_id') is None and (pct, tot, don) == (92, 12, 11),
              f'{pct}% {don}/{tot}')
    else:
        check('PP unassigned backlog counts -> 92% (11/12)', False, str(r.get_json() or {})[:120])
    r = pp_issue(scratch_key, 'PP unassigned done', status='done')
    if r.status_code == 201:
        ids.append(r.get_json()['id'])
        pct, tot, don = pp_val()
        check('PP unassigned done counts -> 92% (12/13)',
              r.get_json().get('assignee_id') is None and (pct, tot, don) == (92, 13, 12),
              f'{pct}% {don}/{tot}')
    else:
        check('PP unassigned done counts -> 92% (12/13)', False, str(r.get_json() or {})[:120])

    # sprint membership must NOT move project progress (sprint % stays separate)
    rs = c.post('/api/v1/sprints', json={'project': scratch_key, 'name': 'PP Sprint 1',
                                         'start_date': '2025-02-01', 'end_date': '2025-03-01',
                                         'goal': 'progress probe'})
    sbid = (rs.get_json() or {}).get('id')
    if rs.status_code == 201 and sbid:
        before_pct = pp_val()[0]
        c.patch(f'/api/v1/issues/{ids[0]}', json={'sprint_id': sbid})
        after_pct = pp_val()[0]
        sap = c.get(f'/api/v1/sprints?project={scratch_key}').get_json() or []
        check('PP sprint membership does not change project progress',
              before_pct == after_pct == 92 and len(sap) >= 1, f'{before_pct}->{after_pct}')
    else:
        check('PP sprint membership does not change project progress', False,
              str(rs.get_json() or {})[:160])

    # work-time/timer activity (earlier sections) leaves progress untouched
    ecm_after = (pp_dash().get(ECOM) or {}).get('progress_percentage')
    check('PP ECOM progress isolated from scratch project', ecm_after == ecm_before,
          f'{ecm_before} -> {ecm_after}')

    # global invariant: every project pcg == round(done/total*100)
    _all = pp_dash()
    inv = all(
        (rp2['progress_percentage'] == (round(rp2['done_issues'] / rp2['total_issues'] * 100)
                                        if rp2['total_issues'] else 0))
        and rp2['progress'] == rp2['progress_percentage']
        and rp2['done_issues'] <= rp2['total_issues']
        for rp2 in _all.values())
    check('PP invariant for every project: progress==round(done/total*100)', inv,
          str({k: v['progress_percentage'] for k, v in _all.items()})[:160])

    # every consumer surface agrees
    row = next((p for p in (c.get('/api/v1/projects').get_json() or []) if p.get('id') == scratch), None)
    check('PP /api/v1/projects consistent', row and row.get('progress_percentage') == 92
          and row.get('done_issues') == 12 and row.get('progress') == 92, str(row)[:160])
    rc = c.get(f'/api/v1/reports/project-health?project_id={scratch}')
    crb = rc.get_json() or {}
    crow = next((x for x in crb.get('projects', []) if x.get('id') == scratch), None)
    check('PP reports project-health consistent', rc.status_code == 200 and crow
          and crow.get('progress') == 92 and crow.get('total_tasks') == 13
          and crow.get('completed') == 12, str(crb)[:200])
    ra = c.post('/api/v1/ai', json={'message': 'summarize the project progress please'})
    ab = ra.get_json() or {}
    check('PP AI assistant uses computed progress', ra.status_code == 200
          and f'{ecm_before}% complete' in ab.get('response', '')
          and 'issues completed' in ab.get('response', ''),
          f'ecm={ecm_before} resp={ab.get("response", "")[:140]}')
    html = c.get(f'/project/{scratch_key}').get_data(as_text=True)
    check('PP overview page shows 92% + counts subtext',
          '92%' in html and '12 of 13 issues completed' in html, '')
    html = c.get('/projects').get_data(as_text=True)
    check('PP projects page uses projects_progress map', scratch_key in html and '92%' in html, '')

    # refresh + logout/login persistence
    d1 = pp_val()[0]
    d2 = pp_val()[0]
    check('PP refresh returns same value', d1 == d2 == 92, f'{d1}->{d2}')
    c.post('/api/v1/auth/logout')
    c.post('/login', json={'email': 'alex@abc.io', 'password': 'password123'})
    d3 = (pp_dash().get(scratch) or {}).get('progress_percentage')
    check('PP persists across logout/login', d3 == 92, f'd3={d3}')

    try:
        _conn = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira')
        _cur = _conn.cursor()
        _cur.execute('SELECT count(*) FROM issues WHERE project_id=%s', (scratch,))
        _t = _cur.fetchone()[0]
        _cur.execute("SELECT count(*) FROM issues WHERE project_id=%s AND status='done'", (scratch,))
        _d = _cur.fetchone()[0]
        _cur.execute('SELECT count(*) FROM sprints WHERE project_id=%s', (scratch,))
        _s = _cur.fetchone()[0]
        _conn.close()
        check('PP PostgreSQL counts match API', (_t, _d, _s) == (13, 12, 1), f'({_t}/{_d} sprints={_s})')
    except Exception as _e:
        check('PP PostgreSQL counts match API', False, str(_e))

r = c.get('/api/v1/projects/99999')
check('PP unknown project -> 404', r.status_code == 404)

# ---- cleanup: delete scratch project + confirm baseline restored ----
if scratch:
    rd = c.delete(f'/api/v1/projects/{scratch}')
    db_ = rd.get_json() or {}
    check('PP delete scratch project', rd.status_code == 200 and db_.get('ok') is True, str(db_)[:160])
    gone = all(p['id'] != scratch for p in (c.get('/api/v1/dashboard').get_json() or {}).get('projects', []))
    check('PP scratch gone from dashboard after delete', gone, '')
else:
    check('PP create scratch project', False, 'no scratch project')
    check('PP delete scratch project', False, 'no scratch project')
    check('PP scratch gone from dashboard after delete', False, 'no scratch project')

# =====================================================================
# Task / Subtask hierarchy — one level, top-level-only progress, gated
# =====================================================================

created_ts_logs = []


def ts_issue(project_key, summary, status='backlog', extra=None, client=c):
    payload = {'summary': summary, 'project': project_key,
               'issue_type': 'Task', 'status': status}
    if extra:
        payload.update(extra)
    return client.post('/api/v1/issues', json=payload)


def ts_delete(issue_id, confirm=False):
    if confirm:
        return c.open(f'/api/v1/issues/{issue_id}', method='DELETE',
                      json={'confirm_subtasks': True})
    return c.delete(f'/api/v1/issues/{issue_id}')


tr = c.post('/api/v1/projects', json={
    'name': 'Subtask Scratch', 'start_date': '2025-01-01',
    'target_date': '2025-12-31', 'manager_id': 1, 'assignees': [1],
})
tb = tr.get_json() or {}
ts_proj = tb.get('id')
ts_key = tb.get('key')
if tr.status_code == 201 and ts_proj:
    check('TS create scratch project', True)
    rp = ts_issue(ts_key, 'TS Parent-1', status='todo')
    parent1 = (rp.get_json() or {})
    if rp.status_code == 201:
        check('TS create top-level parent', True)
        r1 = ts_issue(ts_key, 'TS Child-1a', status='done', extra={'parent_issue_id': parent1['id']})
        r2 = ts_issue(ts_key, 'TS Child-1b', status='backlog', extra={'parent_issue_id': parent1['id']})
        r3 = ts_issue(ts_key, 'TS Child-1c', status='in_progress', extra={'parent_issue_id': parent1['id']})
        ok3 = all(r.status_code == 201 for r in (r1, r2, r3))
        check('TS create three subtasks', ok3,
              f'{r1.status_code},{r2.status_code},{r3.status_code}')
        kids = []
        if ok3:
            kids = [r1.get_json()['id'], r2.get_json()['id'], r3.get_json()['id']]
    else:
        check('TS create top-level parent', False, str(parent1)[:160])
    # -------- one-level rule guardrails --------
    rs = ts_issue(ts_key, 'TS Sub-sub', status='backlog',
                  extra={'parent_issue_id': kids[0] if kids else parent1['id']})
    check('TS subtask-of-subtask -> 400', rs.status_code == 400,
          f'status={rs.status_code}')
    # self-parent rejection (create with parent == own id impossible pre-create) via patch
    rself = None
    if rp.status_code == 201:
        rself = c.patch(f"/api/v1/issues/{parent1['id']}",
                        json={'parent_issue_id': parent1['id']})
        check('TS self-parent -> 400', rself.status_code == 400, f'status={rself.status_code}')
    # cross-project parent rejection
    rcrs = ts_issue(ts_key, 'TS Cross', status='backlog',
                    extra={'parent_issue_id': issue['id']})  # issue from ECOM
    check('TS cross-project parent -> 400', rcrs.status_code == 400, f'status={rcrs.status_code}')
    # -------- issue_dict fields --------
    p1 = c.get(f"/api/v1/issues/{parent1['id']}").get_json() or {}
    check('TS parent dict subtask_count/completed',
          p1.get('subtask_count') == 3 and p1.get('completed_subtasks') == 1
          and p1.get('is_subtask') is False and p1.get('parent_issue_id') is None,
          {k: p1.get(k) for k in ('subtask_count', 'completed_subtasks', 'is_subtask', 'parent_issue_id')})
    if kids:
        sk = c.get(f'/api/v1/issues/{kids[1]}').get_json() or {}
        check('TS subtask dict parent fields',
              sk.get('is_subtask') is True and sk.get('parent_issue_id') == parent1['id']
              and sk.get('parent_key') == f"{ts_key}-{parent1['number']}"
              and sk.get('parent_title') == 'TS Parent-1',
              {k: sk.get(k) for k in ('is_subtask', 'parent_issue_id', 'parent_key', 'parent_title')})
    # -------- top_level list filter --------
    tl = c.get(f'/api/v1/issues?project={ts_key}&top_level=1').get_json() or []
    all_l = c.get(f'/api/v1/issues?project={ts_key}').get_json() or []
    check('TS top_level list returns only parents',
          len(tl) == 1 and all(x.get('parent_issue_id') is None for x in tl)
          and len(all_l) == 4, f'tl={len(tl)} all={len(all_l)}')
    # -------- progress counts top-level only (1 parent todo => 0%) --------
    pct0 = (c.get('/api/v1/dashboard').get_json() or {}).get('projects', [])
    tsrow = next((x for x in pct0 if x.get('id') == ts_proj), {})
    check('TS progress counts top-level only (0/1 -> 0%)',
          tsrow.get('total_issues') == 1 and tsrow.get('done_issues') == 0
          and tsrow.get('progress_percentage') == 0, str(tsrow)[:140])
    # done subtask must not lift progress; moving it back/done stays 0%
    if kids:
        c.open(f'/api/v1/issues/{kids[0]}/move', method='POST', json={'status': 'backlog'})
        c.open(f'/api/v1/issues/{kids[0]}/move', method='POST', json={'status': 'done'})
        tsrow2 = next((x for x in (c.get('/api/v1/dashboard').get_json() or {}).get('projects', [])
                       if x.get('id') == ts_proj), {})
        check('TS subtask status moves do not change project progress', tsrow2.get('progress_percentage') == 0,
              str(tsrow2)[:140])
    # parent status move changes progress — but moving a parent with
    # incomplete subtasks to done first requires confirmation
    if rp.status_code == 201:
        rw = c.open(f"/api/v1/issues/{parent1['id']}/move", method='POST', json={'status': 'done'})
        rwb = rw.get_json() or {}
        check('TS parent move to done blocked while subtasks incomplete',
              rw.status_code == 400 and rwb.get('needs_confirmation') is True
              and rwb.get('incomplete_subtasks') == 2,
              f'status={rw.status_code} body={rwb}')
        rw2 = c.open(f"/api/v1/issues/{parent1['id']}/move", method='POST',
                     json={'status': 'done', 'confirm_incomplete': True})
        check('TS parent move to done after confirmation -> 200',
              rw2.status_code == 200, f'status={rw2.status_code}')
        tsrow3 = next((x for x in (c.get('/api/v1/dashboard').get_json() or {}).get('projects', [])
                       if x.get('id') == ts_proj), {})
        check('TS parent move to done -> 100%', tsrow3.get('progress_percentage') == 100,
              str(tsrow3)[:140])
        c.open(f"/api/v1/issues/{parent1['id']}/move", method='POST', json={'status': 'todo'})
    # -------- delete guardrails --------
    if rp.status_code == 201:
        rd0 = ts_delete(parent1['id'])
        rd0b = rd0.get_json() or {}
        check('TS delete parent no-confirm -> 400 + needs_confirmation',
              rd0.status_code == 400 and rd0b.get('needs_confirmation') is True
              and rd0b.get('subtask_count') == 3,
              f'status={rd0.status_code} body={rd0b}')
    # deleting a subtask needs no confirmation and works
    if kids:
        rdk = ts_delete(kids[2])
        check('TS delete single subtask -> 200', rdk.status_code == 200, f'status={rdk.status_code}')
    # deleting the parent with confirmation removes children too
    if rp.status_code == 201:
        rdc = ts_delete(parent1['id'], confirm=True)
        check('TS delete parent with confirm -> 200', rdc.status_code == 200, f'status={rdc.status_code}')
        kids = []
        tl2 = c.get(f'/api/v1/issues?project={ts_key}&top_level=1').get_json() or []
        left = c.get(f'/api/v1/issues?project={ts_key}').get_json() or []
        check('TS parent+subtasks removed via confirm delete',
              len(tl2) == 0 and len(left) == 0, f'tl={len(tl2)} left={len(left)}')
    # -------- permission gate: 401 anon / 403 non-member --------
    c_anon = app.test_client()
    ra = c_anon.post('/api/v1/issues', json={'summary': 'TS anon', 'project': ts_key})
    check('TS anon create -> 401', ra.status_code == 401, f'status={ra.status_code}')
    # re-add a subtask to have something to gate moves/deletes on
    rp = ts_issue(ts_key, 'TS Parent-2', status='todo')
    parent2 = (rp.get_json() or {}) if rp.status_code == 201 else {}
    kid2 = ts_issue(ts_key, 'TS Child-2a', status='backlog',
                    extra={'parent_issue_id': (parent2 or {}).get('id')})
    kid2id = (kid2.get_json() or {}).get('id') if kid2.status_code == 201 else None
    c_sarah = app.test_client()
    c_sarah.post('/api/v1/auth/login', json={'email': 'sarah@abc.io', 'password': 'password123'})
    rm = c_sarah.post('/api/v1/issues', json={'summary': 'TS outsider', 'project': ts_key})
    check('TS non-member create -> 403', rm.status_code == 403, f'status={rm.status_code}')
    if kid2id:
        rmv = c_sarah.open(f'/api/v1/issues/{kid2id}/move', method='POST', json={'status': 'done'})
        check('TS non-member move -> 403', rmv.status_code == 403, f'status={rmv.status_code}')
        rdel = c_sarah.delete(f'/api/v1/issues/{kid2id}')
        check('TS non-member delete -> 403', rdel.status_code == 403, f'status={rdel.status_code}')
        rp2_iss = c_sarah.patch(f'/api/v1/issues/{kid2id}', json={'priority': 'High'})
        check('TS non-member update -> 403', rp2_iss.status_code == 403, f'status={rp2_iss.status_code}')
    # -------- worklogs on a subtask carry parent context --------
    wl = c.post('/api/v1/worklogs', json={
        'project_id': ts_proj, 'work_date': '2025-06-10',
        'start_time': '09:00', 'end_time': '10:30', 'issue_id': kid2id,
        'description': 'subtask work'})
    wlb = wl.get_json() or {}
    if wl.status_code == 201:
        created_ts_logs.append(wlb.get('work_log', {}).get('id'))
        check('TS manual worklog on subtask -> 201', True)
    else:
        check('TS manual worklog on subtask -> 201', False, str(wlb)[:160])
    whl = (c.get(f'/api/v1/worklogs?project_id={ts_proj}').get_json() or {}).get('work_logs', [])
    wrow = next((x for x in whl if x.get('issue_id') == kid2id), {})
    check('TS worklog dict has parent context',
          wrow.get('is_subtask') is True and wrow.get('parent_key') == f'{ts_key}-{(parent2 or {}).get("number")}'
          and wrow.get('parent_title') == 'TS Parent-2',
          {k: wrow.get(k) for k in ('is_subtask', 'parent_key', 'parent_title')})
    # -------- rendered pages show hierarchy --------
    html = c.get(f'/project/{ts_key}').get_data(as_text=True)
    check('TS overview: server-rendered parent-only with count, expand UI present, subtasks lazy-loaded',
          '1 subtask · 0 completed' in html and 'pt-expand-toggle' in html
          and 'Add Subtask' in html and 'subtask-panel' not in html
          and 'subtask-line' not in html and 'data-toggle-icon' not in html
          and 'TS Child-2a' not in html, '')
    # -------- JS integrity: expandable-subtask engine must keep loading and
    #          loaded rows mutually exclusive (regression: stuck "Loading
    #          subtasks…" below loaded subtasks when ptRenderSubtree appended
    #          rows without clearing the placeholder) --------
    try:
        _pt_js_block = html.split('var PT_EXPANDED = {};', 1)[1].split('Team Work Time', 1)[0].split('</script>', 1)[0]
        check('TS subtask JS: ptRenderSubtree clears subtree before rendering',
              'function ptRenderSubtree' in _pt_js_block
              and _pt_js_block.split('function ptRenderSubtree', 1)[1].split('ptAddRows(row, parentId, html);', 1)[0]
                  .find('ptClearSubtree(') > -1, '')
        check('TS subtask JS: success path caches but only paints when expanded',
              'PT_LOADED[parentId] = parent;' in _pt_js_block
              and 'if (PT_EXPANDED[parentId]) ptRenderSubtree(parentId, parent);' in _pt_js_block, '')
        check('TS subtask JS: expand reuses cache without refetch',
              'if (PT_LOADED[parentId]) {' in _pt_js_block
              and 'ptRenderSubtree(parentId, PT_LOADED[parentId]);' in _pt_js_block
              and 'return;' in _pt_js_block.split('if (PT_LOADED[parentId]) {', 1)[1], '')
        check('TS subtask JS: collapsed-while-loading leaves no painted rows',
              'if (!PT_EXPANDED[parentId]) return;' in _pt_js_block, '')
    except Exception as _pt_e:
        check('TS subtask JS integrity', False, str(_pt_e)[:160])
    html2 = c.get(f'/kanban/{ts_key}').get_data(as_text=True)
    check('TS kanban card subtask chip', 'issue-subtask-chip' in html2, '')
    html3 = c.get(f'/backlog/{ts_key}').get_data(as_text=True)
    check('TS backlog card subtask chip', 'issue-subtask-chip' in html3, '')
    html4 = c.get(f'/issue/{kid2id}').get_data(as_text=True)
    check('TS detail shows parent breadcrumb + subtask chip (no Add Subtask)',
          'Subtask of' in html4 and 'Add Subtask' not in html4, '')
    html5 = c.get(f"/issue/{parent2['id']}").get_data(as_text=True)
    check('TS detail top-level shows subtask panel + Add Subtask',
          'Add Subtask' in html5 and 'TS Child-2a' in html5, '')
    # -------- DB end-state for the scratch project --------
    try:
        _cur = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira').cursor()
        _cur.execute('SELECT count(*) FROM issues WHERE project_id=%s AND parent_issue_id IS NOT NULL', (ts_proj,))
        kids_db = _cur.fetchone()[0]
        _cur.connection.close()
        check('TS DB subtask rows match (1)', kids_db == 1, f'kids={kids_db}')
    except Exception as _e:
        check('TS DB subtask rows match (1)', False, str(_e))
else:
    check('TS create scratch project', False, str(tb)[:160])

for _lid in created_ts_logs:
    try:
        c.delete(f'/api/v1/worklogs/{_lid}')
    except Exception:
        pass

# ---- TS cleanup: delete scratch project + global subtask baseline ----
if tr.status_code == 201 and ts_proj:
    rd = c.delete(f'/api/v1/projects/{ts_proj}')
    db_ = rd.get_json() or {}
    check('TS delete scratch project', rd.status_code == 200 and db_.get('ok') is True, str(db_)[:160])
    try:
        _cur = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira').cursor()
        _cur.execute('SELECT count(*) FROM issues WHERE parent_issue_id IS NOT NULL')
        global_subs = _cur.fetchone()[0]
        _cur.connection.close()
        check('TS global subtask baseline restored (0)', global_subs == 0, f'subs={global_subs}')
    except Exception as _e:
        check('TS global subtask baseline restored (0)', False, str(_e))

# =====================================================================
# TS2 — Hierarchical Task/Subtask flow
# (nested rendering, persistent order, reorder, prev/next, done-guard)
# =====================================================================
tr2 = c.post('/api/v1/projects', json={
    'name': 'Hierarchy Scratch', 'start_date': '2025-01-01',
    'target_date': '2025-12-31', 'manager_id': 1, 'assignees': [1],
})
tb2 = tr2.get_json() or {}
ts2_proj = tb2.get('id')
ts2_key = tb2.get('key')

ts2_parentA = None
ts2_kidsA = []

if tr2.status_code == 201 and ts2_proj:
    check('TS2 create scratch project', True)
    rpA = ts_issue(ts2_key, 'H Parent-A', status='todo')
    if rpA.status_code == 201:
        ts2_parentA = rpA.get_json()
        check('TS2 create top-level parent', True)
        titles = ['H Sub-1', 'H Sub-2', 'H Sub-3', 'H Sub-4']
        orders = []
        ok_created = []
        for t in titles:
            rr = ts_issue(ts2_key, t, status='backlog',
                          extra={'parent_issue_id': ts2_parentA['id']})
            ok_created.append(rr.status_code == 201)
            if rr.status_code == 201:
                body = rr.get_json() or {}
                ts2_kidsA.append(body['id'])
                orders.append(body.get('subtask_order'))
        check('TS2 create four subtasks with auto order 1..4',
              all(ok_created) and orders == [1, 2, 3, 4], f'orders={orders}')
    else:
        check('TS2 create top-level parent', False, str(rpA.get_json())[:160])

    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 parent dict holds ordered subtask list',
          [s['id'] for s in pA.get('subtasks', [])] == ts2_kidsA
          and 'subtask_order' in pA and pA.get('subtask_order') == 0,
          {s['id']: s.get('subtask_order') for s in pA.get('subtasks', [])})

    # -------- rendered pages: overview = top-level only; detail = management --------
    html0 = c.get(f'/project/{ts2_key}').get_data(as_text=True)
    check('TS2 overview shows count + expand UI (no server-side subtask rows)',
          'subtask-panel' not in html0 and 'subtask-line' not in html0
          and 'data-toggle-icon' not in html0
          and '4 subtasks · 0 completed' in html0 and 'pt-expand-toggle' in html0, '')
    check('TS2 expandable subtasks: Add Subtask present, subtasks lazy-loaded (not top-level rows)',
          'Add Subtask' in html0
          and all(f'data-id="{k}"' not in html0 for k in ts2_kidsA)
          and 'H Sub-1' not in html0, '')
    hd0 = c.get(f"/issue/{ts2_parentA['id']}").get_data(as_text=True)
    check('TS2 detail lists subtasks in persisted order with display keys',
          f'{ts2_key}-{ts2_parentA["number"]}-1' in hd0
          and f'{ts2_key}-{ts2_parentA["number"]}-4' in hd0
          and hd0.index('H Sub-1') < hd0.index('H Sub-2') < hd0.index('H Sub-3') < hd0.index('H Sub-4'), '')

    # -------- reorder: move up / down / boundaries / absolute --------
    k1, k2, k3, k4 = ts2_kidsA
    rup = c.open(f'/api/v1/issues/{k3}/reorder', method='POST', json={'direction': 'up'})
    rupb = rup.get_json() or {}
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 move up persists new order',
          rup.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k1, k3, k2, k4]
          and [s['subtask_order'] for s in pA.get('subtasks', [])] == [1, 2, 3, 4],
          [s['id'] for s in pA.get('subtasks', [])])
    pA2 = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 reorder survives second fetch (persisted)',
          [s['id'] for s in pA2.get('subtasks', [])] == [k1, k3, k2, k4],
          [s['id'] for s in pA2.get('subtasks', [])])
    rdw = c.open(f'/api/v1/issues/{k1}/reorder', method='POST', json={'direction': 'down'})
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 move down persists new order',
          rdw.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k3, k1, k2, k4],
          [s['id'] for s in pA.get('subtasks', [])])
    rb_up = c.open(f'/api/v1/issues/{k3}/reorder', method='POST', json={'direction': 'up'})  # first -> stays
    rb_dn = c.open(f'/api/v1/issues/{k4}/reorder', method='POST', json={'direction': 'down'})  # last -> stays
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 boundary moves leave order unchanged',
          rb_up.status_code == 200 and rb_dn.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k3, k1, k2, k4],
          [s['id'] for s in pA.get('subtasks', [])])
    # 'subtask_order: N' moves by swapping with the sibling currently at N
    rabs = c.open(f'/api/v1/issues/{k2}/reorder', method='POST', json={'subtask_order': 1})
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 absolute subtask_order move',
          rabs.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k2, k1, k3, k4],
          [s['id'] for s in pA.get('subtasks', [])])
    rbad = c.open(f'/api/v1/issues/{k4}/reorder', method='POST', json={'direction': 'sideways'})
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 unknown direction leaves order unchanged',
          rbad.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k2, k1, k3, k4],
          [s['id'] for s in pA.get('subtasks', [])])
    rtop = c.open(f"/api/v1/issues/{ts2_parentA['id']}/reorder", method='POST', json={'direction': 'up'})
    check('TS2 reorder top-level task -> 400',
          rtop.status_code == 400, f'status={rtop.status_code}')
    # final rendered order (server source of truth) matches [k2, k1, k3, k4]
    hd1 = c.get(f"/issue/{ts2_parentA['id']}").get_data(as_text=True)
    check('TS2 detail page follows persisted order after reorder',
          hd1.index('H Sub-2') < hd1.index('H Sub-1') < hd1.index('H Sub-3') < hd1.index('H Sub-4'), '')

    # -------- prev/next navigation on the subtask detail page --------
    hk2 = c.get(f'/issue/{k2}').get_data(as_text=True)
    check('TS2 detail shows Subtask 1 of 4 + disabled Previous (first)',
          'Subtask <strong>1</strong> of <strong>4</strong>' in hk2
          and 'disabled title="First subtask"' in hk2
          and f'href="/issue/{k1}"' in hk2, '')
    hk1 = c.get(f'/issue/{k1}').get_data(as_text=True)
    check('TS2 detail shows Subtask 2 of 4 with prev/next links',
          'Subtask <strong>2</strong> of <strong>4</strong>' in hk1
          and f'href="/issue/{k2}"' in hk1 and f'href="/issue/{k3}"' in hk1, '')
    hk4 = c.get(f'/issue/{k4}').get_data(as_text=True)
    check('TS2 last subtask shows disabled Last subtask',
          'Subtask <strong>4</strong> of <strong>4</strong>' in hk4
          and 'disabled>Last subtask' in hk4, '')

    # -------- completion: prompt next subtask, never auto-change parent --------
    m1 = c.open(f'/api/v1/issues/{k3}/move', method='POST', json={'status': 'done'})
    hkm = c.get(f'/issue/{k3}').get_data(as_text=True)
    check('TS2 completed subtask offers Open Next Subtask',
          m1.status_code == 200 and 'Open Next Subtask' in hkm and f'href="/issue/{k4}"' in hkm, '')
    m2 = c.open(f'/api/v1/issues/{k4}/move', method='POST', json={'status': 'done'})
    hkl = c.get(f'/issue/{k4}').get_data(as_text=True)
    check('TS2 last completed subtask points to parent',
          m2.status_code == 200 and 'This was the last subtask' in hkl
          and f'href="/issue/{ts2_parentA["id"]}"' in hkl, '')
    stat = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 subtask completion never auto-changes parent status',
          stat.get('status') == 'todo', stat.get('status'))

    # -------- parent done-guard via update (PATCH) --------
    pg = c.patch(f"/api/v1/issues/{ts2_parentA['id']}", json={'status': 'done'})
    pgb = pg.get_json() or {}
    check('TS2 PATCH parent done while subtasks incomplete -> 400 + warning',
          pg.status_code == 400 and pgb.get('needs_confirmation') is True
          and pgb.get('incomplete_subtasks') == 2,
          f'status={pg.status_code} body={pgb}')
    pg2 = c.patch(f"/api/v1/issues/{ts2_parentA['id']}",
                  json={'status': 'done', 'confirm_incomplete': True})
    check('TS2 PATCH parent done after confirmation -> 200',
          pg2.status_code == 200, f'status={pg2.status_code}')
    c.patch(f"/api/v1/issues/{ts2_parentA['id']}", json={'status': 'todo'})

    # -------- per-parent ordering resets (parent B starts at 1) --------
    rpB = ts_issue(ts2_key, 'H Parent-B', status='todo')
    if rpB.status_code == 201:
        pB = rpB.get_json()
        b = []
        for _i in range(2):
            rb = ts_issue(ts2_key, f'H PB sub {_i + 1}', status='backlog',
                          extra={'parent_issue_id': pB['id']})
            b.append((rb.status_code, (rb.get_json() or {}).get('subtask_order')))
        check('TS2 per-parent orders restart at 1',
              all(s == 201 for s, _o in b) and [o for _s, o in b] == [1, 2], b)
    else:
        check('TS2 per-parent orders restart at 1', False, str(rpB.get_json())[:160])

    # -------- permission gates for reorder --------
    c_anon2 = app.test_client()
    r_anon = c_anon2.open(f'/api/v1/issues/{k1}/reorder', method='POST', json={'direction': 'down'})
    check('TS2 anon reorder -> 401', r_anon.status_code == 401, f'status={r_anon.status_code}')
    c_sarah2 = app.test_client()
    c_sarah2.post('/api/v1/auth/login', json={'email': 'sarah@abc.io', 'password': 'password123'})
    r_out = c_sarah2.open(f'/api/v1/issues/{k1}/reorder', method='POST', json={'direction': 'down'})
    check('TS2 non-member reorder -> 403', r_out.status_code == 403, f'status={r_out.status_code}')

    # -------- delete normalizes sibling order (no gaps) --------
    rdel = ts_delete(k1)
    pA = c.get(f"/api/v1/issues/{ts2_parentA['id']}").get_json() or {}
    check('TS2 single subtask delete -> 200 and siblings renumbered 1..3',
          rdel.status_code == 200 and
          [s['id'] for s in pA.get('subtasks', [])] == [k2, k3, k4]
          and [s['subtask_order'] for s in pA.get('subtasks', [])] == [1, 2, 3],
          [(s['id'], s['subtask_order']) for s in pA.get('subtasks', [])])
    try:
        _cur = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira').cursor()
        _cur.execute(
            'SELECT subtask_order FROM issues WHERE parent_issue_id=%s ORDER BY subtask_order',
            (ts2_parentA['id'],))
        rows = [r[0] for r in _cur.fetchall()]
        _cur.connection.close()
        check('TS2 PostgreSQL subtask_order column normalized', rows == [1, 2, 3],
              f'orders={rows}')
    except Exception as _e:
        check('TS2 PostgreSQL subtask_order column normalized', False, str(_e))

    # -------- swagger + create-subtask bridge --------
    sw = c.get('/swagger.json').get_json() or {}
    check('TS2 swagger documents subtask_order + reorder endpoint',
          'subtask_order' in sw.get('components', {}).get('schemas', {}).get('Issue', {}).get('properties', {})
          and '/api/v1/issues/{issue_id}/reorder' in sw.get('paths', {}),
          list(sw.get('paths', {}).keys()))
    htmlJ = c.get(f'/project/{ts2_key}').get_data(as_text=True)
    htmlK = c.get(f"/issue/{ts2_parentA['id']}").get_data(as_text=True)
    check('TS2 Add Subtask available on overview (expanded) and Task Details',
          'Add Subtask' in htmlJ and 'Add Subtask' in htmlK
          and "'Create Subtask'" in htmlK and 'Parent Task' in htmlK, '')

    # ---- clean scratch projects ----
    rd2 = c.delete(f'/api/v1/projects/{ts2_proj}')
    db2 = rd2.get_json() or {}
    check('TS2 delete scratch project', rd2.status_code == 200 and db2.get('ok') is True, str(db2)[:160])
    try:
        _cur = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira').cursor()
        _cur.execute('SELECT count(*) FROM issues WHERE parent_issue_id IS NOT NULL')
        subs2 = _cur.fetchone()[0]
        _cur.connection.close()
        check('TS2 global subtask baseline restored (0)', subs2 == 0, f'subs={subs2}')
    except Exception as _e:
        check('TS2 global subtask baseline restored (0)', False, str(_e))
else:
    check('TS2 create scratch project', False, str(tb2)[:160])

# =====================================================================
# TS3 — Production-grade: sprint no-double-count, Sprint Next Task,
#       in-place create hook, duplicate-submission guard, TASK header
# =====================================================================
tr3 = c.post('/api/v1/projects', json={
    'name': 'Production Task Screw', 'start_date': '2025-01-01',
    'target_date': '2025-12-31', 'manager_id': 1, 'assignees': [1],
})
tb3 = tr3.get_json() or {}
ts3_proj = tb3.get('id')
ts3_key = tb3.get('key')

if tr3.status_code == 201 and ts3_proj:
    check('TS3 create scratch project', True)

    t_ids = []
    t_ids_ok = True
    for t in ['Sprint Task-1', 'Sprint Task-2', 'Sprint Task-3']:
        rr = ts_issue(ts3_key, t, status='todo')
        if rr.status_code == 201:
            t_ids.append(rr.get_json()['id'])
        else:
            t_ids_ok = False
    check('TS3 create three sprint top-level tasks', t_ids_ok and len(t_ids) == 3, f'ids={t_ids}')

    rs3 = c.post('/api/v1/sprints', json={'project': ts3_key, 'name': 'TS3 Sprint',
                                          'start_date': '2025-02-01', 'end_date': '2025-02-28'})
    sb3 = (rs3.get_json() or {}).get('id') if rs3.status_code == 201 else None
    check('TS3 create sprint', rs3.status_code == 201 and sb3 is not None, f'status={rs3.status_code}')

    assign_sprint_ok = True
    for tid in t_ids:
        rp = c.patch(f'/api/v1/issues/{tid}', json={'sprint_id': sb3})
        if rp.status_code != 200:
            assign_sprint_ok = False
    check('TS3 assign three tasks to sprint', assign_sprint_ok, '')

    s1 = ts_issue(ts3_key, 'TS3 Sub-A', status='done', extra={'parent_issue_id': t_ids[0]})
    s2 = ts_issue(ts3_key, 'TS3 Sub-B', status='backlog', extra={'parent_issue_id': t_ids[0]})
    s1id = (s1.get_json() or {}).get('id')
    s2id = (s2.get_json() or {}).get('id')
    subs_ok = s1.status_code == 201 and s2.status_code == 201
    subs_sprint = True
    for sid in [s1id, s2id]:
        rp = c.patch(f'/api/v1/issues/{sid}', json={'sprint_id': sb3})
        if rp.status_code != 200:
            subs_sprint = False
    check('TS3 create subtasks also in the sprint container',
          subs_ok and subs_sprint and s1id and s2id,
          f'{s1.status_code}/{s2.status_code}')

    # Sprint accounting is TOP-LEVEL ONLY: parent + its subtasks are never
    # double-counted even when the subtasks carry the same sprint assignment.
    sp3 = {}
    rsp = c.get(f'/api/v1/sprints?project={ts3_key}')
    if rsp.status_code == 200:
        sp3 = next((x for x in (rsp.get_json() or []) if x.get('id') == sb3), {})
    check('TS3 sprint total counts top-level tasks only (3, not 5)',
          sp3.get('total') == 3, f"total={sp3.get('total')}")
    check('TS3 sprint done counts top-level only (0; subtask done not counted)',
          sp3.get('done') == 0, f"done={sp3.get('done')}")

    pA3 = c.get(f"/api/v1/issues/{t_ids[0]}").get_json() or {}
    check('TS3 subtask_count reflects children (2) and done (1)',
          pA3.get('subtask_count') == 2 and pA3.get('completed_subtasks') == 1,
          f"count={pA3.get('subtask_count')} done={pA3.get('completed_subtasks')}")

    # Last subtask of a sprint task done -> optional "Open Next Task" prompt
    # pointing at the next top-level task in the same Sprint (no redirect).
    mS2 = c.open(f'/api/v1/issues/{s2id}/move', method='POST', json={'status': 'done'})
    hS2 = c.get(f'/issue/{s2id}').get_data(as_text=True)
    t2 = c.get(f"/api/v1/issues/{t_ids[1]}").get_json() or {}
    check('TS3 last subtask done offers Open Next Task (sprint sibling)',
          mS2.status_code == 200 and 'Open Next Task' in hS2
          and 'Next task in the current Sprint' in hS2
          and f'href="/issue/{t_ids[1]}"' in hS2,
          f'move={mS2.status_code}')
    check('TS3 next-task anchor carries the next task key',
          f'Open Next Task: {t2.get("key")}' in hS2, t2.get('key'))
    stat3 = c.get(f"/api/v1/issues/{t_ids[0]}").get_json() or {}
    check('TS3 sprint next-task never auto-changes parent status',
          stat3.get('status') == 'todo', stat3.get('status'))

    htmlP = c.get(f'/project/{ts3_key}').get_data(as_text=True)
    check('TS3 Project Tasks table uses TASK header',
          '<th>Task</th>' in htmlP and '<th>Objective</th>' not in htmlP, '')
    check('TS3 overview: top-level tasks + expand UI, subtasks lazy-loaded, in-place hook def present',
          'subtask-panel' not in htmlP and 'data-toggle-icon' not in htmlP
          and 'subtask-line' not in htmlP
          and 'window.WT_AFTER_ISSUE_CREATE = function' in htmlP
          and 'Add Subtask' in htmlP
          and 'TS3 Sub-A' not in htmlP and 'TS3 Sub-B' not in htmlP, '')
    check('TS3 overview shows real subtask counts from PostgreSQL',
          '2 subtasks · 2 completed' in htmlP, '')
    hdT1 = c.get(f"/issue/{t_ids[0]}").get_data(as_text=True)
    check('TS3 Task Details manages subtasks (Add Subtask + persisted order)',
          'Add Subtask' in hdT1 and 'TS3 Sub-A' in hdT1 and 'TS3 Sub-B' in hdT1
          and '2 of 2 completed' in hdT1, '')
    hdT3 = c.get(f"/issue/{t_ids[2]}").get_data(as_text=True)
    check('TS3 empty-subtask Task shows clean empty state',
          'Add Subtask' in hdT3 and '0 of 0 completed' in hdT3
          and 'No subtasks yet. Break this task into smaller pieces.' in hdT3, '')
    check('TS3 create modal guards duplicate submission + after-create hook',
          'if (ciSubmitting) return;' in htmlP
          and 'Creating…' in htmlP
          and 'WT_AFTER_ISSUE_CREATE(d, payload.parent_issue_id, opts.project)' in htmlP, '')

    rd3 = c.delete(f'/api/v1/projects/{ts3_proj}')
    db3 = rd3.get_json() or {}
    check('TS3 delete scratch project', rd3.status_code == 200 and db3.get('ok') is True, str(db3)[:160])
    try:
        _cur = _pg3.connect('postgresql://wexira:wexira@127.0.0.1:5432/wexira').cursor()
        _cur.execute('SELECT count(*) FROM issues WHERE parent_issue_id IS NOT NULL')
        subs3 = _cur.fetchone()[0]
        _cur.connection.close()
        check('TS3 global subtask baseline restored (0)', subs3 == 0, f'subs={subs3}')
    except Exception as _e:
        check('TS3 global subtask baseline restored (0)', False, str(_e))
else:
    check('TS3 create scratch project', False, str(tb3)[:160])

print(f'\n=== {len(PASS)} passed, {len(FAIL)} failed ===')
if FAIL:
    print('FAILED:', FAIL)
    sys.exit(1)