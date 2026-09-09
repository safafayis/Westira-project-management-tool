from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    initials = db.Column(db.String(8), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default='lite')
    role = db.Column(db.String(80), nullable=False)
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


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(12), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default='')
    lead_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    lead_initials = db.Column(db.String(8))
    color = db.Column(db.String(20), default='#4f46e5')
    status = db.Column(db.String(40), default='In Progress')
    start_date = db.Column(db.String(40))
    due_date = db.Column(db.String(40))
    progress = db.Column(db.Integer, default=0)
    health_schedule = db.Column(db.String(40), default='On Track')
    health_budget = db.Column(db.String(40), default='On Track')
    health_scope = db.Column(db.String(40), default='On Track')
    health_capacity = db.Column(db.String(40), default='Good')

    lead = db.relationship('User', foreign_keys=[lead_id])


class ProjectMembers(db.Model):
    __tablename__ = 'project_members'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))


class Sprint(db.Model):
    __tablename__ = 'sprints'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(80))
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    start_date = db.Column(db.String(40))
    end_date = db.Column(db.String(40))
    goal = db.Column(db.String(160))
    status = db.Column(db.String(40), default='Planned')
    to_do = db.Column(db.Integer, default=0)
    in_progress = db.Column(db.Integer, default=0)
    in_review = db.Column(db.Integer, default=0)
    done = db.Column(db.Integer, default=0)
    story_points_total = db.Column(db.Integer, default=0)
    story_points_done = db.Column(db.Integer, default=0)


class Issue(db.Model):
    __tablename__ = 'issues'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    number = db.Column(db.Integer)
    title = db.Column(db.String(240), nullable=False)
    issue_type = db.Column(db.String(40), default='Story')
    type_color = db.Column(db.String(20), default='#4f46e5')
    priority = db.Column(db.String(20), default='Medium')
    priority_color = db.Column(db.String(20), default='#0891b2')
    points = db.Column(db.Integer, default=0)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    assignee_initials = db.Column(db.String(8))
    assignee_color = db.Column(db.String(20), default='#4f46e5')
    due_date = db.Column(db.String(40))
    labels = db.Column(db.JSON, default=list)
    status = db.Column(db.String(40), default='backlog')
    position = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default='')
    acceptance_criteria = db.Column(db.Text, default='')
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sprint_id = db.Column(db.Integer, db.ForeignKey('sprints.id'))
    created_at = db.Column(db.String(40), default=lambda: datetime.now().strftime('%b %d, %Y'))

    assignee = db.relationship('User', foreign_keys=[assignee_id])
    project = db.relationship('Project', foreign_keys=[project_id])
    sprint = db.relationship('Sprint', foreign_keys=[sprint_id])
    reporter = db.relationship('User', foreign_keys=[reporter_id])


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.String(40), default=lambda: datetime.now().strftime('%b %d, %Y'))

    author = db.relationship('User', foreign_keys=[author_id])


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(20), default='plus')
    color = db.Column(db.String(20), default='#4f46e5')
    text = db.Column(db.String(240))
    detail = db.Column(db.String(240))
    time = db.Column(db.String(40))


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(20), default='bell')
    color = db.Column(db.String(20), default='#4f46e5')
    title = db.Column(db.String(240))
    detail = db.Column(db.String(240))
    notification_type = db.Column(db.String(20), default='updates')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(40))