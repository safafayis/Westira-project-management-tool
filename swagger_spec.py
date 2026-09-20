"""
OpenAPI 3.0 specification builder for the ABC Project API.

Each API endpoint carries its own documentation through the ``@api_doc``
decorator (wraps the endpoint function with its operation metadata right where
the endpoint is defined).  ``build_openapi_spec(app)`` walks ``app.url_map``
to include every ``/api/`` route automatically, then reads the metadata back
off each endpoint function.  Any route without a wrapper gets a generic entry
so no endpoint is ever silently missing from the docs.
"""
import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _path(rule):
    """Flask path ``<int:issue_id>`` → OpenAPI ``{issue_id}``."""
    return re.sub(r'<(?:\w+:)?([^>]+)>', r'{\1}', rule)


def _param(name, location, schema, desc='', required=False):
    return {
        'name': name, 'in': location, 'required': required,
        'schema': schema, 'description': desc,
    }


def _q(name, schema, desc='', required=False):
    return _param(name, 'query', schema, desc, required)


def _p(name, schema, desc=''):
    return _param(name, 'path', schema, desc, True)


def _body(schema, required=True):
    return {'required': required, 'content': {'application/json': {'schema': schema}}}


def _ok(ref=None, desc='Success'):
    schema = {'$ref': ref} if ref else {}
    return {'description': desc, 'content': {'application/json': {'schema': schema}}}


def _err(codes=(400, 401, 403, 404, 409)):
    out = {}
    for c in codes:
        label = {400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                 404: 'Not Found', 409: 'Conflict'}.get(c, 'Error')
        out[str(c)] = {'description': label,
                       'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}}
    return out


def _only_ok():
    return {'200': {'description': 'Success', 'content': {'application/json': {}}}}


# Common query filters used by every Reports endpoint
_REPORT_Q = [
    _q('project_id', {'type': 'integer'}, 'Filter by project ID'),
    _q('sprint_id', {'type': 'integer'}, 'Filter by sprint ID'),
    _q('assignee_id', {'type': 'integer'}, 'Filter by assignee user ID'),
    _q('status', {'type': 'string', 'enum': ['backlog', 'todo', 'in_progress', 'in_review', 'done']},
       'Filter by issue status'),
    _q('start_date', {'type': 'string', 'format': 'date'}, 'Start of date range (YYYY-MM-DD)'),
    _q('end_date', {'type': 'string', 'format': 'date'}, 'End of date range (YYYY-MM-DD)'),
]


# ---------------------------------------------------------------------------
# Component schemas  (mirrors the serializers in app.py)
# ---------------------------------------------------------------------------

SCHEMAS = {
    'User': {
        'type': 'object',
        'properties': {
            'id':              {'type': 'integer'},
            'name':            {'type': 'string'},
            'initials':        {'type': 'string'},
            'role':            {'type': 'string'},
            'team':            {'type': 'string'},
            'email':           {'type': 'string', 'format': 'email'},
            'color':           {'type': 'string', 'example': '#4f46e5'},
            'plan':            {'type': 'string', 'enum': ['pro', 'plus', 'lite']},
            'capacity':        {'type': 'integer', 'description': 'Workload capacity %'},
            'active_projects': {'type': 'integer'},
            'current_tasks':   {'type': 'integer'},
            'status':          {'type': 'string', 'example': 'Active'},
            'is_online':       {'type': 'boolean'},
            'last_seen':       {'type': 'string', 'nullable': True, 'format': 'date-time'},
            'created_at':      {'type': 'string', 'nullable': True, 'format': 'date-time'},
        },
    },
    'Issue': {
        'type': 'object',
        'properties': {
            'id':                      {'type': 'integer'},
            'project':                 {'type': 'string', 'description': 'Project key'},
            'number':                  {'type': 'integer'},
            'key':                     {'type': 'string', 'example': 'ECOM-42'},
            'title':                   {'type': 'string'},
            'type':                    {'type': 'string', 'enum': ['Story', 'Bug', 'Task', 'Epic']},
            'type_color':              {'type': 'string'},
            'priority':                {'type': 'string', 'enum': ['Critical', 'Highest', 'High', 'Medium', 'Low', 'Lowest']},
            'priority_color':          {'type': 'string'},
            'points':                  {'type': 'integer'},
            'assignee_id':             {'type': 'integer', 'nullable': True},
            'assignee':                {'type': 'string', 'description': 'Primary assignee initials'},
            'assignee_color':          {'type': 'string'},
            'assignee_initials_list':  {'type': 'array', 'items': {'type': 'string'}},
            'due':                     {'type': 'string', 'nullable': True},
            'start':                   {'type': 'string', 'nullable': True},
            'labels':                  {'type': 'array', 'items': {'type': 'string'}},
            'status':                  {'type': 'string', 'enum': ['backlog', 'todo', 'in_progress', 'in_review', 'done']},
            'sprint':                  {'type': 'integer', 'nullable': True, 'description': 'Sprint number'},
            'sprint_name':            {'type': 'string', 'nullable': True, 'description': 'Human-readable sprint display name, e.g. "Sprint 13"'},
            'description':             {'type': 'string'},
            'acceptance_criteria':     {'type': 'string'},
            'reporter':                {'type': 'integer', 'nullable': True, 'description': 'Reporter user ID'},
            'created':                 {'type': 'string', 'nullable': True},
            'working_minutes':         {'type': 'integer', 'nullable': True, 'description': 'Task Working Hours total (integer minutes). Only meaningful when status is done; NULL = not recorded. This single value is the source of truth for Team Work Time.'},
            'working_text':            {'type': 'string', 'nullable': True, 'description': 'Formatted working hours ("4h 30m"); null unless status is done and working_minutes is set'},
            'parent_issue_id':         {'type': 'integer', 'nullable': True, 'description': 'NULL = top-level Task; otherwise the id of the parent top-level Task (single Subtask level)'},
            'is_subtask':              {'type': 'boolean', 'description': 'True when the issue is a Subtask (parent_issue_id set)'},
            'subtask_order':           {'type': 'integer', 'description': 'Persistent 1-based order among the parent task\'s subtasks (0 for top-level tasks)'},
            'parent_key':              {'type': 'string', 'nullable': True, 'description': 'Parent display key, e.g. ECOM-42'},
            'parent_title':            {'type': 'string', 'nullable': True, 'description': 'Parent task title'},
            'subtask_count':           {'type': 'integer', 'description': 'Number of subtasks (top-level tasks only)'},
            'completed_subtasks':      {'type': 'integer', 'description': 'Completed subtasks (top-level tasks only)'},
            'subtasks':                {'type': 'array', 'description': 'Ordered subtask summaries (top-level tasks only)', 'items': {'type': 'object', 'properties': {
                'id':                {'type': 'integer'},
                'number':            {'type': 'integer'},
                'key':               {'type': 'string'},
                'title':             {'type': 'string'},
                'status':            {'type': 'string'},
                'points':            {'type': 'integer'},
                'subtask_order':     {'type': 'integer'},
            }}},
        },
    },
    'Project': {
        'type': 'object',
        'properties': {
            'id':              {'type': 'integer'},
            'key':             {'type': 'string', 'example': 'ECOM'},
            'name':            {'type': 'string'},
            'lead_id':         {'type': 'integer', 'nullable': True},
            'lead_initials':   {'type': 'string', 'nullable': True},
            'color':           {'type': 'string'},
            'status':          {'type': 'string'},
            'start_date':      {'type': 'string'},
            'due_date':        {'type': 'string'},
            'progress':        {'type': 'integer', 'description': 'Percentage 0-100 (completed top-level tasks / total top-level tasks; subtasks excluded)'},
            'progress_percentage': {'type': 'integer', 'description': 'Percentage 0-100 (alias of progress)'},
            'description':     {'type': 'string'},
            'health':          {'type': 'object'},
            'members':         {'type': 'array', 'items': {'$ref': '#/components/schemas/User'}},
            'member_count':    {'type': 'integer'},
            'total_issues':    {'type': 'integer'},
            'done_issues':     {'type': 'integer'},
        },
    },
    'Sprint': {
        'type': 'object',
        'properties': {
            'id':                   {'type': 'integer'},
            'number':               {'type': 'integer'},
            'name':                 {'type': 'string'},
            'project':              {'type': 'string', 'nullable': True, 'description': 'Project key'},
            'project_id':           {'type': 'integer'},
            'status':               {'type': 'string', 'enum': ['Planning', 'Active', 'Completed']},
            'start_date':           {'type': 'string'},
            'end_date':             {'type': 'string'},
            'goal':                 {'type': 'string'},
            'description':          {'type': 'string'},
            'to_do':                {'type': 'integer'},
            'in_progress':          {'type': 'integer'},
            'in_review':            {'type': 'integer'},
            'done':                 {'type': 'integer'},
            'backlog':              {'type': 'integer'},
            'total':                {'type': 'integer'},
            'remaining':            {'type': 'integer'},
            'progress':             {'type': 'integer'},
            'story_points_total':   {'type': 'integer'},
            'story_points_done':    {'type': 'integer'},
            'tasks':                {'type': 'array', 'items': {'$ref': '#/components/schemas/Issue'}},
        },
    },
    'Comment': {
        'type': 'object',
        'properties': {
            'id':              {'type': 'integer'},
            'body':            {'type': 'string'},
            'author_id':       {'type': 'integer'},
            'author':          {'type': 'string'},
            'author_initials': {'type': 'string'},
            'author_color':    {'type': 'string'},
            'issue_id':        {'type': 'integer'},
            'created_at':      {'type': 'string'},
        },
    },
    'WorkLog': {
        'type': 'object',
        'properties': {
            'id':               {'type': 'integer'},
            'project_id':       {'type': 'integer'},
            'issue_id':         {'type': 'integer', 'nullable': True},
            'issue_key':        {'type': 'string', 'nullable': True, 'example': 'ECOM-142'},
            'worked_by_user_id':  {'type': 'integer'},
            'worked_by_name':     {'type': 'string'},
            'worked_by_initials': {'type': 'string'},
            'worked_by_color':    {'type': 'string'},
            'logged_by_user_id':  {'type': 'integer'},
            'logged_by_name':     {'type': 'string'},
            'work_date':        {'type': 'string', 'format': 'date'},
            'start_time':       {'type': 'string', 'nullable': True, 'example': '10:00'},
            'end_time':         {'type': 'string', 'nullable': True, 'example': '12:30'},
            'duration_minutes': {'type': 'integer'},
            'duration_text':    {'type': 'string', 'example': '2h 30m'},
            'description':      {'type': 'string'},
            'created_at':       {'type': 'string', 'format': 'date-time'},
            'updated_at':       {'type': 'string', 'format': 'date-time'},
        },
    },
    'WorkTimer': {
        'type': 'object',
        'properties': {
            'id':               {'type': 'integer'},
            'user_id':          {'type': 'integer'},
            'project_id':       {'type': 'integer'},
            'project_key':      {'type': 'string', 'example': 'ECOM'},
            'issue_id':         {'type': 'integer'},
            'issue_key':        {'type': 'string', 'example': 'ECOM-167'},
            'issue_title':      {'type': 'string'},
            'started_at':       {'type': 'string', 'format': 'date-time', 'description': 'Server timestamp (UTC)'},
            'server_now':       {'type': 'string', 'format': 'date-time', 'description': 'Server timestamp returned with the payload'},
            'elapsed_minutes':  {'type': 'integer', 'nullable': True},
            'elapsed_seconds':  {'type': 'integer', 'nullable': True},
            'stopped_at':       {'type': 'string', 'format': 'date-time', 'nullable': True},
            'work_log_id':      {'type': 'integer', 'nullable': True},
        },
    },
    'WorkTimerActive': {
        'type': 'object',
        'properties': {
            'ok':     {'type': 'boolean'},
            'active': {'type': 'boolean'},
            'timer':  {'oneOf': [{'$ref': '#/components/schemas/WorkTimer'}, {'type': 'null'}]},
        },
    },
    'WorkTimeSummary': {
        'type': 'object',
        'properties': {
            'ok':           {'type': 'boolean'},
            'project_id':   {'type': 'integer'},
            'project_key':  {'type': 'string'},
            'today':        {'type': 'string', 'format': 'date'},
            'current_user_id': {'type': 'integer'},
            'can_log_for_others': {'type': 'boolean'},
            'members':      {'type': 'array', 'items': {'type': 'object'}},
            'totals':       {'type': 'object'},
        },
    },
    'Notification': {
        'type': 'object',
        'description': 'Notification object (shape varies by notification type)',
        'additionalProperties': True,
    },
    'Dashboard': {
        'type': 'object',
        'properties': {
            'user':               {'$ref': '#/components/schemas/User'},
            'kpis':               {'type': 'array'},
            'projects':           {'type': 'array', 'items': {'$ref': '#/components/schemas/Project'}},
            'active_sprint':      {'oneOf': [{'$ref': '#/components/schemas/Sprint'}, {'type': 'null'}]},
            'my_tasks':           {'type': 'array', 'items': {'$ref': '#/components/schemas/Issue'}},
            'recent_activities':  {'type': 'array'},
        },
    },
    'Error': {
        'type': 'object',
        'properties': {
            'ok':    {'type': 'boolean', 'enum': [False]},
            'error': {'type': 'string'},
        },
    },
}


# ---------------------------------------------------------------------------
# api_doc — wraps an endpoint function with its OpenAPI operation metadata.
# Used inside app.py directly above each API endpoint definition.
# ---------------------------------------------------------------------------

def api_doc(summary, tags=None, params=None, req=None, resp=None, desc=''):
    """Wrap an API endpoint with its OpenAPI operation metadata.

    Decorator applied directly above an endpoint function (below @app.route /
    @login_required).  build_openapi_spec() reads this off the view function
    when generating /swagger.json, so every endpoint documents itself inline.
    """
    def deco(fn):
        body = {'summary': summary, 'tags': tags or []}
        if desc:
            body['description'] = desc
        if params:
            body['parameters'] = params
        if req:
            body['requestBody'] = _body(req)
        body['responses'] = resp or _only_ok()
        fn._openapi = body
        return fn
    return deco


# ---------------------------------------------------------------------------
# Spec builder — called once per request, walks url_map so new endpoints
# are never silently omitted.  Operation metadata is read from the @api_doc
# wrapper attached to each endpoint function.
# ---------------------------------------------------------------------------

def _generic_operation(method, path):
    """Fallback operation for an endpoint that has no @api_doc wrapper."""
    tag = 'Other'
    rel = path[len('/api/v1'):] if path.startswith('/api/v1') else path
    for t in ('Issues', 'Comments', 'Notifications', 'Users & Team',
              'Projects', 'Sprints', 'Reports', 'AI Assistant'):
        if rel.startswith('/api/' + {
            'Issues': 'issues', 'Comments': 'comments',
            'Notifications': 'notifications', 'Users & Team': 'users',
            'Projects': 'projects', 'Sprints': 'sprints',
            'Reports': 'reports', 'AI Assistant': 'ai',
        }.get(t, '')):
            tag = t
            break
    return {
        'summary':  f'{method.upper()} {path}',
        'tags':     [tag],
        'responses': {'200': {'description': 'Success', 'content': {'application/json': {}}}},
    }


def _endpoint_openapi(app, rule, method):
    """Operation dict for one endpoint: prefer the function's @api_doc wrapper
    (unwrapping decorators like @login_required), otherwise a generic fallback."""
    fn = app.view_functions.get(rule.endpoint)
    while fn is not None:
        meta = getattr(fn, '_openapi', None)
        if meta is not None:
            return dict(meta)
        fn = getattr(fn, '__wrapped__', None)
    return _generic_operation(method, _path(rule.rule))


def build_openapi_spec(app):
    """Return a complete OpenAPI 3.0.3 dict for all /api/ routes."""
    spec = {
        'openapi': '3.0.3',
        'info': {
            'title':       'ABC Project API',
            'version':     '1.0.0',
            'description': 'REST API for the ABC Project Management platform.  '
                           'All endpoints under ``/api/v1`` are documented here.  '
                           'Authentication is cookie-based (Flask session).',
        },
        'servers': [{'url': '', 'description': 'Current origin'}],
        'tags': [
            {'name': 'Authentication', 'description': 'Login, logout, current user'},
            {'name': 'Dashboard',      'description': 'Dashboard data'},
            {'name': 'Issues',         'description': 'Issue CRUD, Kanban move'},
            {'name': 'Comments',       'description': 'Issue comments'},
            {'name': 'Notifications',  'description': 'User notifications'},
            {'name': 'Users & Team',   'description': 'User management and team roles'},
            {'name': 'Projects',       'description': 'Project management'},
            {'name': 'Work Logs',      'description': 'Project-scoped team work time'},
            {'name': 'Sprints',        'description': 'Sprint lifecycle'},
            {'name': 'AI Assistant',   'description': 'AI assistant chat'},
            {'name': 'Reports',        'description': 'Analytics and reporting'},
        ],
        'paths': {},
        'components': {
            'schemas': SCHEMAS,
            'securitySchemes': {
                'cookieAuth': {
                    'type': 'apiKey',
                    'in':   'cookie',
                    'name': 'session',
                    'description': 'Flask session cookie (set after POST /api/v1/auth/login)',
                },
            },
        },
        'security': [{'cookieAuth': []}],
    }

    seen = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api/'):
            continue
        if rule.endpoint in ('static', 'swagger_json'):
            continue
        path = _path(rule.rule)
        methods = rule.methods - {'HEAD', 'OPTIONS'}
        if path not in spec['paths']:
            spec['paths'][path] = {}
        for m in methods:
            lmethod = m.lower()
            key = (path, lmethod)
            if key in seen:
                continue
            seen.add(key)
            spec['paths'][path][lmethod] = _endpoint_openapi(app, rule, m)

    return spec