from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from werkzeug.exceptions import abort

from app.services import issue_service
from swagger_spec import _err, _ok, _p, api_doc

comments_bp = Blueprint('comments', __name__, url_prefix='/comments')


@comments_bp.post('')
@login_required
@api_doc('Add comment', ['Comments'],
    req={'type': 'object',
         'required': ['issue_id', 'body'],
         'properties': {
             'issue_id': {'type': 'integer'},
             'body':     {'type': 'string'},
         }},
    resp={'201': _ok('#/components/schemas/Comment', 'Created'), **_err([400, 401])})
def add_comment():
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.add_comment(data, current_user)
    return jsonify(resp), status


@comments_bp.get('/<int:comment_id>')
@login_required
@api_doc('Get comment', ['Comments'],
    params=[_p('comment_id', {'type': 'integer'}, 'Comment ID')],
    resp={'200': _ok('#/components/schemas/Comment'), **_err([401, 404])})
def get_comment(comment_id):
    return jsonify(issue_service.get_comment(comment_id))


@comments_bp.put('/<int:comment_id>')
@login_required
@api_doc('Update comment', ['Comments'],
    params=[_p('comment_id', {'type': 'integer'}, 'Comment ID')],
    req={'type': 'object', 'required': ['body'], 'properties': {'body': {'type': 'string'}}},
    resp={'200': _ok('#/components/schemas/Comment'), **_err([400, 401, 403])})
def update_comment(comment_id):
    comment = issue_service.get_comment(comment_id)
    if comment.get('author_id') != current_user.id:
        abort(403)
    data = request.get_json(silent=True) or {}
    resp, status = issue_service.update_comment(comment_id, data, current_user)
    return jsonify(resp), status


@comments_bp.delete('/<int:comment_id>')
@login_required
@api_doc('Delete comment', ['Comments'],
    params=[_p('comment_id', {'type': 'integer'}, 'Comment ID')],
    resp={'200': {'description': 'Deleted', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}}}},
          **_err([401, 403, 404])})
def delete_comment(comment_id):
    comment = issue_service.get_comment(comment_id)
    if comment.get('author_id') != current_user.id:
        abort(403)
    return jsonify(issue_service.delete_comment(comment_id))