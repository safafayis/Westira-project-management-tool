from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from werkzeug.exceptions import abort

from app.models import Notification
from app.services import notification_service
from swagger_spec import _err, _ok, _p, _q, api_doc

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')


@notifications_bp.get('')
@login_required
@api_doc('List notifications', ['Notifications'],
    params=[
        _q('category', {'type': 'string', 'enum': ['all', 'assigned', 'mentions', 'updates']}, 'Filter by category', False),
        _q('read',     {'type': 'string', 'enum': ['true', 'false']}, 'Filter by read status'),
        _q('q',        {'type': 'string'}, 'Search notifications'),
        _q('page',     {'type': 'integer', 'default': 1}, 'Page number'),
        _q('limit',    {'type': 'integer', 'default': 20, 'maximum': 50}, 'Results per page'),
    ],
    resp={'200': _ok(None, 'Paginated notifications list'), **_err([401])})
def list_notifications():
    return jsonify(notification_service.list_notifications(current_user, request.args))


@notifications_bp.get('/unread-count')
@login_required
@api_doc('Get unread count', ['Notifications'],
    resp={'200': {'description': 'Count breakdown',
                  'content': {'application/json': {
                      'schema': {'type': 'object',
                                 'properties': {
                                     'count':     {'type': 'integer'},
                                     'mentions':  {'type': 'integer'},
                                     'assigned':  {'type': 'integer'},
                                     'updates':   {'type': 'integer'},
                                 }}}}}})
def unread_count():
    return jsonify(notification_service.unread_count_breakdown(current_user))


@notifications_bp.patch('/<int:nid>/read')
@login_required
@api_doc('Mark notification read', ['Notifications'],
    params=[_p('nid', {'type': 'integer'}, 'Notification ID')],
    resp={'200': _ok(), **_err([401, 403, 404])})
def mark_read(nid):
    n = Notification.query.get_or_404(nid)
    if n.recipient_id != current_user.id:
        abort(403)
    notification_service.mark_as_read(n)
    return jsonify({'ok': True})


@notifications_bp.patch('/read-all')
@login_required
@api_doc('Mark all notifications read', ['Notifications'],
    resp={'200': {'description': 'OK', 'content': {'application/json': {
              'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'count': {'type': 'integer'}}}}}}})
def mark_read_all():
    count = notification_service.mark_all_as_read(current_user)
    return jsonify({'ok': True, 'count': count})


@notifications_bp.delete('/<int:nid>')
@login_required
@api_doc('Delete notification', ['Notifications'],
    params=[_p('nid', {'type': 'integer'}, 'Notification ID')],
    resp={'200': _ok(), **_err([401, 403, 404])})
def delete_notification(nid):
    n = Notification.query.get_or_404(nid)
    if n.recipient_id != current_user.id:
        abort(403)
    notification_service.soft_delete(n)
    return jsonify({'ok': True})