"""End-to-end verification of the route-aware sidebar active state.

Logs in via the real app (test client), opens every HTML page route, and
asserts that the rendered sidebar highlights exactly the expected section
based only on the URL route. Every request is a fresh server render, so the
same pass also validates direct-URL access, refresh, Back/Forward and
query-string variants.
"""
import re
import sys

sys.path.insert(0, r'C:\Users\SAFA FAYIS\sample_flaskapi_api')

from app import create_app  # noqa: E402

PASS = []
FAIL = []


def check(name, ok, extra=''):
    (PASS if ok else FAIL).append(name)
    print(f'[{"PASS" if ok else "FAIL"}] {name}' + (f'  -> {extra}' if extra and not ok else ''))


def active_nav_hrefs(html):
    """Hrefs of sidebar items that carry the is-active class."""
    out = []
    for m in re.finditer(r'<a href="([^"]+)" class="wf-nav-item[^"]*"', html):
        if 'is-active' in m.group(0):
            out.append(m.group(1))
    return out


def main():
    app = create_app()
    c = app.test_client()

    r = c.post('/login', json={'email': 'alex@abc.io', 'password': 'password123'})
    check('login alex', r.status_code == 200 and r.get_json().get('ok') is True,
          f'status={r.status_code}')

    me = c.get('/api/v1/auth/me').get_json()
    plan = me.get('plan', '')
    check('auth/me', bool(me.get('email')), str(me)[:120])

    projects = c.get('/api/v1/projects').get_json()
    key = projects[0]['key']
    issue_id = c.get('/api/v1/issues').get_json()[0]['id']
    print(f'  -> using project key={key!r} issue_id={issue_id} plan={plan!r}\n')

    # (path, expected active href; None expected href => no active margin)
    cases = [
        ('/dashboard', '/dashboard'),
        ('/dashboard?project=' + key, '/dashboard'),        # query params must not break
        ('/projects', '/projects'),
        ('/project', '/projects'),                          # project detail (no key)
        ('/project/' + key, '/projects'),                   # PROJECT DETAIL
        ('/project/' + key + '?sprint_id=0', '/projects'),  # child page with query
        ('/project/' + key + '?tab=tasks', '/projects'),    # query params
        ('/issue/' + str(issue_id), '/projects'),           # project issue detail
        ('/issue', '/projects'),                            # issue default
        ('/my-work', '/my-work'),
        ('/kanban', '/kanban'),
        ('/kanban/' + key, '/kanban'),
        ('/backlog', '/backlog'),
        ('/backlog/' + key, '/backlog'),
        ('/sprints', '/sprints'),
        ('/sprints/' + key, '/sprints'),
        ('/ai-assistant', '/ai-assistant'),
        ('/reports', '/reports'),
        ('/team', '/team'),
        ('/notifications', '/notifications'),
        # No sidebar representation -> exactly zero active items.
        ('/calendar', None),
    ]
    if plan == 'pro':
        cases.append(('/people-hub', '/team'))

    for path, expected_href in cases:
        r = c.get(path)
        if r.status_code != 200:
            check(f'GET {path} renders', False,
                  f'status={r.status_code} loc={r.headers.get("Location")}')
            continue
        check(f'GET {path} renders', True)
        active = active_nav_hrefs(r.get_data(as_text=True))
        if expected_href is None:
            check(f'   {path} -> NO active nav item', len(active) == 0, f'active={active}')
        else:
            check(f'   {path} -> exactly one active: {expected_href}',
                  len(active) == 1 and active[0] == expected_href, f'active={active}')

    print(f'\nTotal: {len(PASS)} passed, {len(FAIL)} failed')
    if FAIL:
        print('FAILED:')
        for f in FAIL:
            print('  -', f)
        sys.exit(1)


if __name__ == '__main__':
    main()