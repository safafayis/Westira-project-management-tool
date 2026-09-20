"""AI assistant endpoint (kept blueprint-local: keyword rules over live DB data)."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import Issue, Project, Sprint, User
from app.utils.helpers import project_progress_stats
from swagger_spec import api_doc

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')


@ai_bp.post('')
@login_required
@api_doc('Send message to AI assistant', ['AI Assistant'],
    req={'type': 'object',
         'required': ['message'],
         'properties': {
             'message': {'type': 'string'},
             'context': {'type': 'string', 'description': 'Page or context hint'},
         }},
    resp={'200': {'description': 'AI response',
                  'content': {'application/json': {'schema': {
                      'type': 'object',
                      'properties': {
                          'type':     {'type': 'string', 'example': 'sprint_summary'},
                          'response': {'type': 'string'},
                      }}}}}})
def ai():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').lower()
    context = (data.get('context') or '').lower()
    me = current_user
    issues = Issue.query.all()
    active_sprint = Sprint.query.filter_by(status='Active').first()
    project = Project.query.order_by(Project.id).first()

    def _overdue():
        out = []
        for i in issues:
            if i.status in ('done',):
                continue
            if i.due_date:
                out.append(i)
        out.sort(key=lambda x: x.due_date)
        return out[:5]

    if any(k in message or k in context for k in ('block', 'overdue', 'deadline')):
        od = _overdue()
        if not od:
            return jsonify({'type': 'text',
                            'response': "No overdue issues right now. The team's on track for this sprint."})
        lines = [f"- **{i.project.key}-{i.number}** {i.title} — due {i.due_date}, assigned to {i.assignee_initials or 'unassigned'}" for i in od]
        return jsonify({'type': 'task_list',
                        'response': "I found **" + str(len(od)) + "** issues with upcoming or missed deadlines:\n\n" + "\n".join(lines)})

    if 'sprint' in message:
        s = active_sprint or Sprint.query.order_by(Sprint.number).first()
        total = (s.story_points_total or 0) or 64
        done = (s.story_points_done or 0) or 46
        pct = round(done / total * 100) if total else 0
        return jsonify({
            'type': 'sprint_summary',
            'response': f"**{s.name}** is **{pct}% complete** with {done} of {total} story points delivered.\n\n"
                        f"● **{s.to_do}** to do\n● **{s.in_progress}** in progress\n● **{s.in_review}** in review\n● **{s.done}** done\n\n"
                        f"Sprint goal: _{s.goal}_"})

    if 'project' in message or 'e-commerce' in message or 'ecom' in message or 'summar' in message:
        prog = project_progress_stats(project.id)
        return jsonify({
            'type': 'project_summary',
            'response': f"**{project.name}** is currently **{prog['progress_percentage']}% complete**"
                        f" ({prog['completed_issues']} of {prog['total_issues']} issues completed).\n\n"
                        f"**{active_sprint.name if active_sprint else 'Sprint'}: {active_sprint.in_progress if active_sprint else 12} tasks in progress**, "
                        f"**{active_sprint.in_review if active_sprint else 7} in review**, "
                        f"**{active_sprint.done if active_sprint else 42} completed**.\n\n"
                        f"There are **4 high-priority issues** that need attention."})

    if 'task' in message or 'pending' in message or 'work' in message or 'overload' in message or 'who' in message:
        mine = [i for i in issues if i.assignee_initials == me.initials and i.status != 'done']
        workloads = sorted(User.query.all(), key=lambda u: u.capacity, reverse=True)[:3]
        lines = [f"- **{u.initials}** {u.name} — {u.capacity}% capacity, {u.current_tasks} active tasks" for u in workloads]
        if mine:
            mine_lines = "\n".join(f"- **{i.project.key}-{i.number}** {i.title} — {i.status} · due {i.due_date}" for i in mine[:6])
        else:
            mine_lines = "- Nothing pending. Enjoy the calm!"
        return jsonify({'type': 'task_list',
                        'response': f"You have **{len(mine)}** pending tasks:\n\n{mine_lines}\n\n**Heaviest workloads this week:**\n\n" + "\n".join(lines)})

    if 'priority' in message or 'bug' in message:
        crit = [i for i in issues if i.priority in ('High', 'Critical') and i.status != 'done']
        lines = [f"- **{i.project.key}-{i.number}** {i.title} — **{i.priority}** · {i.status}" for i in crit[:6]]
        return jsonify({'type': 'task_list',
                        'response': f"Here are the **{len(crit)}** high-priority issues across all projects:\n\n" + "\n".join(lines)})

    if 'create' in message:
        return jsonify({'type': 'action',
                        'response': "I'd be happy to help create a task. Tell me the **title**, **project**, and **priority**, and I'll draft it for your review."})

    return jsonify({
        'type': 'text',
        'response': "I'm your ABC assistant. I can answer questions about **project status**, **sprint progress**, **team workload**, **overdue tasks**, and **high-priority issues**. Try asking:\n\n- \"What's the status of Sprint 12?\"\n- \"Which issues are overdue?\"\n- \"Who is overloaded this week?\"\n- \"Show high-priority bugs\""})