"""Application factory for the refactored ABC workspace.

Replaces the old ``app.py`` monolith: extensions are initialized here and
configuration / routes / startup bootstrap are composed into a Flask app.
"""
import os
from datetime import datetime

from flask import Flask, jsonify, redirect, request, url_for
from flask_login import current_user as login_current_user
from flask_login import login_user, logout_user
from flask_swagger_ui import get_swaggerui_blueprint

from app.api.v1 import ALL_API_BLUEPRINTS
from app.config import Config
from app.extensions import db, login_manager
from app.models import Project, User
from app.routes.pages import register_pages
from app.utils.bootstrap import bootstrap_database
from app.utils.helpers import _workspace_name, active_section_for, context_project, minutes_text

# ------------------------------------------------------------------
# Auth hooks
# ------------------------------------------------------------------


def _init_auth(app):
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Please sign in to continue.'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        """JSON 401 for API requests (so the frontend fetch helper can redirect
        on 401), preserving the standard login redirect for HTML navigation."""
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Authentication required.'}), 401
        return redirect(url_for('login'))

    return app


# ------------------------------------------------------------------
# Request lifecycle
# ------------------------------------------------------------------


def _init_request_hooks(app):

    @app.before_request
    def update_last_seen():
        if login_current_user.is_authenticated:
            if login_current_user.status and login_current_user.status.lower() != 'active':
                logout_user()
                if request.endpoint and request.endpoint != 'login':
                    return redirect(url_for('login'))
                return None
            now = datetime.utcnow()
            if not login_current_user.last_seen or (now - login_current_user.last_seen).total_seconds() > 60:
                login_current_user.last_seen = now
                db.session.commit()

    @app.context_processor
    def inject_globals():
        cu = login_current_user if login_current_user.is_authenticated else None
        auth_pages = ('login', 'register', 'static')
        show_project = request.endpoint not in auth_pages and cu is not None
        return {
            'current_user': cu,
            'workspace_name': _workspace_name(),
            'project': context_project() if show_project else (Project.query.first() if request.endpoint in ('login', 'register') else None),
            'projects_list': Project.query.all() if cu else [],
            'minutes_text': minutes_text,
            'active_section': active_section_for(request.endpoint),
        }

    return app


# ------------------------------------------------------------------
# Swagger UI
# ------------------------------------------------------------------

SWAGGER_URL = '/swagger'
API_URL = '/swagger.json'


def _init_swagger(app):
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={
            'app_name': 'ABC Project API',
            'docExpansion': 'list',
            'filter': True,
            'deepLinking': True,
        },
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

    @app.route(API_URL)
    def swagger_json():
        from swagger_spec import build_openapi_spec
        return jsonify(build_openapi_spec(app))

    return app


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def create_app():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'templates'),
        static_folder=os.path.join(project_root, 'static'),
    )
    app.config.from_object(Config)

    db.init_app(app)

    _init_auth(app)
    _init_request_hooks(app)
    _init_swagger(app)

    for bp in ALL_API_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix='/api/v1' + (bp.url_prefix or ''))

    register_pages(app)

    bootstrap_database(app)

    return app