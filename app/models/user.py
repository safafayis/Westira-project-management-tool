from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    initials = db.Column(db.String(8), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default='lite')
    role = db.Column(db.String(80), nullable=False)
    permission_role = db.Column(db.String(40), nullable=False, default='member')
    team = db.Column(db.String(80), nullable=False)
    capacity = db.Column(db.Integer, default=70)
    active_projects = db.Column(db.Integer, default=1)
    current_tasks = db.Column(db.Integer, default=0)
    color = db.Column(db.String(20), default='#4f46e5')
    status = db.Column(db.String(40), default='Active')
    last_seen = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserNotificationPreferences(db.Model):
    __tablename__ = 'user_notification_preferences'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    mentions = db.Column(db.Boolean, default=True)
    assignments = db.Column(db.Boolean, default=True)
    status_changes = db.Column(db.Boolean, default=True)
    comments = db.Column(db.Boolean, default=True)
    sprint_updates = db.Column(db.Boolean, default=True)
    due_date_reminders = db.Column(db.Boolean, default=True)
    overdue = db.Column(db.Boolean, default=True)
    project_updates = db.Column(db.Boolean, default=True)
    system = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])

    @property
    def as_dict(self):
        keys = ('mentions', 'assignments', 'status_changes', 'comments',
                'sprint_updates', 'due_date_reminders', 'overdue',
                'project_updates', 'system')
        return {k: bool(getattr(self, k)) for k in keys}