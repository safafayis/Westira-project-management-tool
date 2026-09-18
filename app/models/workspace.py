from datetime import datetime

from app.extensions import db


class WorkspaceSettings(db.Model):
    """Singleton row (id always 1) holding workspace-level preferences.

    These values are *defaults*: they only apply to projects/issues created
    after a change, and never rewrite existing records.
    """
    __tablename__ = 'workspace_settings'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, default='ABC')
    slug = db.Column(db.String(80), unique=True, nullable=False, default='abc-workspace')
    domain = db.Column(db.String(120), default='')
    logo_path = db.Column(db.String(240), default='')
    logo_color = db.Column(db.String(20), default='#4f46e5')
    description = db.Column(db.Text, default='')
    default_issue_type = db.Column(db.String(40), default='Story')
    default_priority = db.Column(db.String(20), default='Medium')
    default_status = db.Column(db.String(20), default='todo')
    default_project_visibility = db.Column(db.String(20), default='private')
    timezone = db.Column(db.String(40), default='UTC-5 (Eastern)')
    date_format = db.Column(db.String(20), default='%b %d, %Y')
    working_days = db.Column(db.JSON, default=lambda: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)