from datetime import datetime

from app.extensions import db


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'))
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.String(40), default=lambda: datetime.now().strftime('%b %d, %Y'))

    author = db.relationship('User', foreign_keys=[author_id])