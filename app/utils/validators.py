"""Backend validation for the various date-range rules."""
from app.utils.helpers import parse_date


def validate_task_dates(project, start_date, end_date):
    """Validate a task's dates fall within the project date range.

    Returns (ok, error_message).
    """
    p_start = parse_date(project.start_date)
    p_end = parse_date(project.due_date)
    t_start = parse_date(start_date)
    t_end = parse_date(end_date)

    if t_start and t_end and t_end < t_start:
        return False, "Task target date cannot be earlier than the task start date."
    if p_start and t_start and t_start < p_start:
        return False, "Task start date cannot be earlier than the project start date."
    if p_end and t_start and t_start > p_end:
        return False, "Task start date cannot be later than the project target date."
    if p_start and t_end and t_end < p_start:
        return False, "Target Date cannot be earlier than the project start date."
    if p_end and t_end and t_end > p_end:
        return False, "Target Date cannot be later than the project target date."
    return True, None


def validate_project_dates(start_date, end_date):
    """Project target date must not be earlier than project start date."""
    s = parse_date(start_date)
    e = parse_date(end_date)
    if s and e and e < s:
        return False, "Project target date cannot be earlier than the project start date."
    return True, None


def validate_sprint_dates(start_date, end_date):
    """End date must be strictly after the start date."""
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start and end and end <= start:
        return False
    return True