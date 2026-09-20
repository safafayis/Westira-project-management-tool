from datetime import datetime

from app.extensions import db
from app.models.user import User


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
    start_date = db.Column(db.String(40))
    labels = db.Column(db.JSON, default=list)
    status = db.Column(db.String(40), default='backlog')
    position = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default='')
    acceptance_criteria = db.Column(db.Text, default='')
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sprint_id = db.Column(db.Integer, db.ForeignKey('sprints.id'))
    created_at = db.Column(db.String(40), default=lambda: datetime.now().strftime('%b %d, %Y'))
    completed_at = db.Column(db.DateTime, nullable=True)
    # Task Working Hours: total minutes recorded against a completed task.
    # Only meaningful when status == 'done' (enforced in the service layer);
    # NULL means "not recorded" and is shown as em dash in the UI.
    working_minutes = db.Column(db.Integer, nullable=True)
    # Task/Subtask hierarchy (single level): NULL = top-level Task,
    # otherwise the id of the project Task this issue is a Subtask of.
    parent_issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'), nullable=True)
    # Persistent ordering index among a parent task's subtasks (1..N).
    subtask_order = db.Column(db.Integer, default=0)

    assignee = db.relationship('User', foreign_keys=[assignee_id])
    project = db.relationship('Project', foreign_keys=[project_id])
    sprint = db.relationship('Sprint', foreign_keys=[sprint_id])
    reporter = db.relationship('User', foreign_keys=[reporter_id])
    assignee_links = db.relationship('IssueAssignees', backref='issue', lazy='select')
    parent_issue = db.relationship(
        'Issue', remote_side=[id], foreign_keys=[parent_issue_id],
        backref=db.backref('subtasks', lazy='select',
                           order_by='Issue.subtask_order, Issue.position, Issue.id'))

    @property
    def all_assignee_initials(self):
        initials = []
        if self.assignee_initials:
            initials.append(self.assignee_initials)
        for link in self.assignee_links or []:
            user = User.query.get(link.user_id)
            if user and user.initials not in initials:
                initials.append(user.initials)
        return ','.join(initials).lower()

    @property
    def assignee_avatars(self):
        """Ordered list of unique assignee avatars for display on cards.

        Each entry is {'initials', 'color', 'name'} derived from real user rows.
        """
        avatars = []
        seen = set()
        if self.assignee_id or self.assignee_initials:
            user = User.query.get(self.assignee_id) if self.assignee_id else None
            initials = (user.initials if user else self.assignee_initials) or ''
            if initials and initials not in seen:
                seen.add(initials)
                avatars.append({
                    'initials': initials,
                    'color': user.color if user else self.assignee_color,
                    'name': user.name if user else '',
                })
        for link in self.assignee_links or []:
            user = User.query.get(link.user_id)
            if not user:
                continue
            if user.initials in seen:
                continue
            seen.add(user.initials)
            avatars.append({
                'initials': user.initials,
                'color': user.color,
                'name': user.name,
            })
        return avatars


class IssueAssignees(db.Model):
    __tablename__ = 'issue_assignees'

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))