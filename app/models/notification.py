from datetime import datetime

from app.extensions import db


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notif_recipient_read', 'recipient_id', 'is_read'),
        db.Index('ix_notif_recipient_created', 'recipient_id', 'created_dt'),
        db.Index('ix_notif_recipient_category', 'recipient_id', 'category'),
    )

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(20), default='bell')
    color = db.Column(db.String(20), default='#4f46e5')
    title = db.Column(db.String(240))
    detail = db.Column(db.String(240))
    message = db.Column(db.Text, default='')
    notification_type = db.Column(db.String(20), default='updates')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(40))
    created_dt = db.Column(db.DateTime, default=datetime.utcnow)

    type = db.Column(db.String(40), default='system')
    category = db.Column(db.String(20), default='updates')
    priority = db.Column(db.String(20), default='normal')

    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'))
    sprint_id = db.Column(db.Integer, db.ForeignKey('sprints.id'))
    event_key = db.Column(db.String(200), unique=True, index=True)
    meta = db.Column('metadata', db.JSON, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    recipient = db.relationship('User', foreign_keys=[recipient_id])
    actor = db.relationship('User', foreign_keys=[actor_id])
    project = db.relationship('Project', foreign_keys=[project_id])
    issue = db.relationship('Issue', foreign_keys=[issue_id])
    sprint = db.relationship('Sprint', foreign_keys=[sprint_id])