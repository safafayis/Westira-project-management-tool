from app.extensions import db


class Sprint(db.Model):
    __tablename__ = 'sprints'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(80))
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    start_date = db.Column(db.String(40))
    end_date = db.Column(db.String(40))
    goal = db.Column(db.String(160))
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(40), default='Planned')
    to_do = db.Column(db.Integer, default=0)
    in_progress = db.Column(db.Integer, default=0)
    in_review = db.Column(db.Integer, default=0)
    done = db.Column(db.Integer, default=0)
    story_points_total = db.Column(db.Integer, default=0)
    story_points_done = db.Column(db.Integer, default=0)

    project = db.relationship('Project', foreign_keys=[project_id])