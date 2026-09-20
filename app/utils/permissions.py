"""Plan / permission checks shared across the API layer."""


def is_pro(user):
    """True when the user is on the 'pro' plan (People Hub & team management)."""
    return bool(user) and getattr(user, 'plan', None) == 'pro'


def can_manage_team_members(user):
    """The single authorization rule for team member management.

    ONLY a Project Manager on the 'pro' plan may add/edit/activate/deactivate
    team members. This is enforced by the Flask backend (never trusted from
    frontend/localStorage/request body values).
    """
    return (
        bool(user)
        and getattr(user, 'plan', None) == 'pro'
        and getattr(user, 'role', None) == 'Project Manager'
    )