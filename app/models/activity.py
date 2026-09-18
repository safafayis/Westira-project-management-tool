from app.extensions import db


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    icon = db.Column(db.String(20), default='plus')
    color = db.Column(db.String(20), default='#4f46e5')
    text = db.Column(db.String(240))
    detail = db.Column(db.String(240))
    time = db.Column(db.String(40))