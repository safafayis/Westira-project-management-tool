from app.extensions import db


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