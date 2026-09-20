from app.api.v1.ai import ai_bp
from app.api.v1.auth import auth_bp
from app.api.v1.comments import comments_bp
from app.api.v1.dashboard import dashboard_bp
from app.api.v1.issues import issues_bp
from app.api.v1.notifications import notifications_bp
from app.api.v1.projects import projects_bp
from app.api.v1.reports import reports_bp
from app.api.v1.sprints import sprints_bp
from app.api.v1.team import team_bp, users_bp
from app.api.v1.worklogs import worklogs_bp

ALL_API_BLUEPRINTS = (
    auth_bp,
    dashboard_bp,
    issues_bp,
    comments_bp,
    sprints_bp,
    projects_bp,
    users_bp,
    team_bp,
    notifications_bp,
    reports_bp,
    ai_bp,
    worklogs_bp,
)

__all__ = [
    'ALL_API_BLUEPRINTS',
    'ai_bp', 'auth_bp', 'comments_bp', 'dashboard_bp', 'issues_bp',
    'notifications_bp', 'projects_bp', 'reports_bp', 'sprints_bp',
    'team_bp', 'users_bp', 'worklogs_bp',
]