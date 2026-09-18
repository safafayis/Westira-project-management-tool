"""Plan / permission checks shared across the API layer."""


def is_pro(user):
    """True when the user is on the 'pro' plan (People Hub & team management)."""
    return bool(user) and getattr(user, 'plan', None) == 'pro'