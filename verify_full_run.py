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

# --- swagger ---
r = c.get('/swagger.json')
spec = r.get_json()
api_paths = [p for p in spec['paths'] if p.startswith('/api/v1')]
check('GET /swagger.json', r.status_code == 200 and len(api_paths) == 39, f'api paths={len(api_paths)}')

# --- unauthorized API returns JSON 401 ---
c2 = app.test_client()
r = c2.get('/api/v1/notifications')
check('unauth API -> JSON 401', r.status_code == 401 and r.is_json)

# --- pro gate: lite user cannot create users ---
c3 = app.test_client()
r = c3.post('/api/v1/auth/login', json={'email': 'david@wexira.io', 'password': 'password123'})
if r.status_code == 200:
    r = c3.post('/api/v1/users', json={'name': 'X', 'email': 'x@wexira.io', 'password': 'xxxxxx', 'role': 'Dev'})
    check('non-pro create user -> 403', r.status_code == 403)
else:
    check('non-pro create user -> 403', False, f'login failed status={r.status_code}')

print(f'\n=== {len(PASS)} passed, {len(FAIL)} failed ===')
if FAIL:
    print('FAILED:', FAIL)
    sys.exit(1)