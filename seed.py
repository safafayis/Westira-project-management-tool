"""Seed Wexira PostgreSQL database with demo data.

Usage:
    env\\Scripts\\python.exe seed.py
"""
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask

from models import (
    Activity,
    Comment,
    Issue,
    Notification,
    Project,
    ProjectMembers,
    Sprint,
    User,
    db,
)

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'postgresql://wexira:wexira@127.0.0.1:5432/wexira'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ----------------------------------------------------------
        # USERS
        # ----------------------------------------------------------
        users_data = [
            # name, initials, email, role, plan, team, cap, ap, ct, color
            ('Alex Morgan', 'AM', 'alex@wexira.io', 'Project Manager', 'pro', 'Platform', 85, 3, 8, '#4f46e5'),
            ('Sarah Chen', 'SC', 'sarah@wexira.io', 'Frontend Developer', 'pro', 'Checkout', 90, 2, 12, '#0891b2'),
            ('Marcus Johnson', 'MJ', 'marcus@wexira.io', 'Backend Developer', 'plus', 'Platform', 75, 2, 10, '#059669'),
            ('Priya Sharma', 'PS', 'priya@wexira.io', 'UI/UX Designer', 'plus', 'Checkout', 60, 2, 6, '#d97706'),
            ('David Kim', 'DK', 'david@wexira.io', 'QA Engineer', 'lite', 'Quality', 95, 1, 15, '#7c3aed'),
            ('Emily Rodriguez', 'ER', 'emily@wexira.io', 'Product Manager', 'lite', 'Product', 50, 1, 4, '#dc2626'),
            ('James Wilson', 'JW', 'james@wexira.io', 'DevOps Engineer', 'lite', 'Infrastructure', 45, 2, 7, '#0d9488'),
            ('Olivia Brown', 'OB', 'olivia@wexira.io', 'Frontend Developer', 'plus', 'Storefront', 70, 1, 5, '#db2777'),
        ]
        users = {}
        now = datetime.utcnow()
        for name, initials, email, role, plan, team, cap, ap, ct, color in users_data:
            u = User(name=name, initials=initials, email=email, role=role, plan=plan, team=team,
                     capacity=cap, active_projects=ap, current_tasks=ct, color=color,
                     created_at=now - timedelta(days=30))
            u.set_password('password123')
            db.session.add(u)
            db.session.flush()
            users[initials] = u

        users['AM'].last_seen = now - timedelta(minutes=2)
        users['SC'].last_seen = now - timedelta(minutes=4)
        users['MJ'].last_seen = now - timedelta(hours=3)
        users['PS'].last_seen = now - timedelta(hours=1)
        users['DK'].last_seen = now - timedelta(days=1)
        users['ER'].last_seen = now - timedelta(days=2)
        users['JW'].last_seen = now - timedelta(hours=12)
        users['OB'].last_seen = now - timedelta(minutes=8)

        # ----------------------------------------------------------
        # PROJECTS
        # ----------------------------------------------------------
        projects_data = [
            ('ECOM', 'E-Commerce Platform', 'AM', '#4f46e5', 'In Progress', 'Jan 12, 2026', 'Dec 30, 2026', 68,
             'On Track', 'On Track', 'At Risk', 'Good',
             'Build the next-generation e-commerce platform with modern checkout, order tracking, and recommendation engine.'),
            ('BANK', 'Mobile Banking App', 'ER', '#0891b2', 'In Progress', 'Mar 03, 2026', 'Nov 30, 2026', 42,
             'On Track', 'At Risk', 'On Track', 'Good',
             'Secure mobile banking experience with biometric auth, instant transfers, and spending insights.'),
            ('SUPT', 'Customer Support Portal', 'SC', '#059669', 'In Progress', 'Nov 10, 2025', 'Aug 31, 2026', 81,
             'On Track', 'On Track', 'On Track', 'Good',
             'Unified customer support portal with ticketing, knowledge base, and live chat.'),
            ('AIPL', 'AI Analytics Platform', 'MJ', '#7c3aed', 'Not Started', 'May 15, 2026', 'Feb 28, 2027', 25,
             'At Risk', 'On Track', 'On Track', 'Limited',
             'Analytics platform powered by machine learning for predictive insights and anomaly detection.'),
            ('HRMS', 'Internal HR System', 'OB', '#d97706', 'Completed', 'Sep 01, 2025', 'May 15, 2026', 95,
             'On Track', 'On Track', 'On Track', 'Good',
             'Internal HR system for onboarding, payroll, leave management, and performance reviews.'),
        ]
        projects = {}
        for (key, name, lead, color, status, start, due, prog,
             hs, hb, hsc, hcap, desc) in projects_data:
            p = Project(key=key, name=name, lead_id=users[lead].id, lead_initials=lead, color=color,
                        status=status, start_date=start, due_date=due, progress=prog,
                        health_schedule=hs, health_budget=hb, health_scope=hsc, health_capacity=hcap,
                        description=desc)
            db.session.add(p)
            db.session.flush()
            projects[key] = p

        # memberships
        member_map = {
            'ECOM': ['AM', 'SC', 'MJ', 'PS', 'DK', 'OB'],
            'BANK': ['ER', 'MJ', 'JW', 'DK'],
            'SUPT': ['SC', 'DK', 'PS'],
            'AIPL': ['MJ', 'ER', 'JW'],
            'HRMS': ['OB', 'PS'],
        }
        for key, initials in member_map.items():
            for ini in initials:
                db.session.add(ProjectMembers(project_id=projects[key].id, user_id=users[ini].id))

        # ----------------------------------------------------------
        # SPRINTS
        # ----------------------------------------------------------
        sprints_data = [
            (11, 58, 58, 'Sep 01, 2026', 'Sep 14, 2026', 'Payment integration', 'Completed', 0, 0, 0, 55),
            (12, 64, 46, 'Sep 01, 2026', 'Sep 14, 2026', 'Complete checkout flow', 'Active', 18, 12, 7, 42),
            (13, 52, 0, 'Sep 15, 2026', 'Sep 28, 2026', 'Search optimization', 'Planned', 30, 0, 0, 0),
            (14, 48, 0, 'Sep 29, 2026', 'Oct 12, 2026', 'Mobile enhancements', 'Planned', 28, 0, 0, 0),
            (15, 44, 0, 'Oct 13, 2026', 'Oct 26, 2026', 'Performance & QA', 'Planned', 26, 0, 0, 0),
        ]
        sprints = {}
        for num, total, done, start, end, goal, status, todo, ip, ir, d in sprints_data:
            s = Sprint(number=num, name=f'Sprint {num}', project_id=projects['ECOM'].id,
                       start_date=start, end_date=end, goal=goal, status=status,
                       to_do=todo, in_progress=ip, in_review=ir, done=d,
                       story_points_total=total, story_points_done=done)
            db.session.add(s)
            db.session.flush()
            sprints[num] = s

        # ----------------------------------------------------------
        # ISSUES
        # ----------------------------------------------------------
        issues_data = [
            # number, project, title, type, tcolor, priority, pcolor, points, assignee, due, status, sprint, position, labels
            (142, 'ECOM', 'Implement checkout API', 'Story', '#059669', 'High', '#d97706', 5, 'SC', 'Sep 08', 'in_progress', 12, 0,
             ['backend', 'api'], 'Implement the REST API endpoints for the checkout flow, including cart validation and order creation.\n\nThe checkout service must handle:\n- Validate cart contents and stock availability\n- Apply promotions and tax\n- Create order with payment details\n- Emit order-confirmed event to the notification service',
             'Given an active cart\nWhen the user taps checkout\nThen the API validates stock and creates an order with status PENDING_PAYMENT'),
            (143, 'ECOM', 'Design payment confirmation', 'Story', '#059669', 'Medium', '#0891b2', 3, 'PS', 'Sep 09', 'in_progress', 12, 1,
             ['ui', 'frontend'], 'Create the payment confirmation screen with order summary and receipt details.',
             'Payment confirmation screen shows order number, items, totals, and a downloadable receipt.'),
            (144, 'ECOM', 'Fix cart quantity bug', 'Bug', '#dc2626', 'High', '#d97706', 2, 'MJ', 'Sep 07', 'in_review', 12, 2,
             ['bug', 'cart'], 'Cart quantity updates incorrectly when items are added rapidly in quick succession.',
             'Rapid add-to-cart from the product page updates the badge to the correct final quantity.'),
            (145, 'ECOM', 'Add order tracking', 'Story', '#059669', 'Medium', '#0891b2', 5, 'OB', 'Sep 11', 'todo', 13, 3,
             ['frontend', 'feature'], 'Add real-time order tracking with shipment status updates and delivery estimates.',
             'Customers can view live shipment status and a delivery date estimate on the order detail screen.'),
            (146, 'ECOM', 'Improve product search', 'Story', '#059669', 'Low', '#4f46e5', 3, 'MJ', 'Sep 12', 'todo', 13, 4,
             ['search', 'backend'], 'Enhance search relevance with typo tolerance and facet filtering.',
             'Search returns relevant results for misspelled queries and supports facet filters for category and price.'),
            (147, 'ECOM', 'Improve mobile checkout', 'Task', '#4f46e5', 'Medium', '#0891b2', 3, 'SC', 'Sep 13', 'backlog', None, 5,
             ['mobile', 'ui'], 'Optimize the checkout process for mobile devices with simplified form inputs.',
             'Mobile checkout can be completed with a maximum of 3 steps and keyboard-optimized inputs.'),
            (148, 'ECOM', 'Payment validation error', 'Bug', '#dc2626', 'Critical', '#dc2626', 2, 'DK', 'Sep 07', 'in_progress', 12, 6,
             ['bug', 'payment'], 'Payment forms silently fail validation when credit card expiry is invalid. Error message is not shown to the user.',
             'Invalid card expiry shows a visible inline error and disables the Pay button.'),
            (149, 'ECOM', 'Update checkout UI', 'Task', '#4f46e5', 'Medium', '#0891b2', 3, 'PS', 'Sep 14', 'backlog', None, 7,
             ['ui', 'frontend'], 'Refresh the checkout UI with the new design system components.',
             'Checkout screens conform to the Wexira design system with accessible contrast.'),
            (150, 'ECOM', 'Set up CI pipeline', 'Task', '#4f46e5', 'High', '#d97706', 2, 'JW', 'Sep 06', 'done', 11, 8,
             ['devops', 'ci'], 'Configure the CI/CD pipeline with automated tests and deployment.',
             'CI runs unit and e2e tests on every push and deploys to staging on merge to main.'),
            (151, 'ECOM', 'Database migration v2', 'Story', '#059669', 'High', '#d97706', 8, 'MJ', 'Sep 08', 'done', 11, 9,
             ['backend', 'database'], 'Migrate the product catalog to the new database schema.',
             'Catalog data migrated to v2 schema with zero downtime and rollback plan documented.'),
            (152, 'ECOM', 'Write API documentation', 'Task', '#4f46e5', 'Low', '#4f46e5', 2, 'SC', 'Sep 05', 'done', 11, 10,
             ['docs', 'api'], 'Document all public API endpoints with examples and schemas.',
             'All public endpoints documented with request/response examples.'),
        ]
        reports = None
        for (num, proj, title, itype, tcolor, prio, pcolor, pts, assignee,
             due, status, sprint_num, pos, labels, desc, criteria) in issues_data:
            i = Issue(
                project_id=projects[proj].id, number=num, title=title, issue_type=itype,
                type_color=tcolor, priority=prio, priority_color=pcolor, points=pts,
                assignee_id=users[assignee].id if assignee else None,
                assignee_initials=assignee, assignee_color=users[assignee].color if assignee else '#9ca3af',
                due_date=due, labels=labels, status=status, position=pos,
                description=desc, acceptance_criteria=criteria,
                reporter_id=users['AM'].id,
                sprint_id=sprints[sprint_num].id if sprint_num else None,
            )
            db.session.add(i)
            db.session.flush()

        # extra backlog-only issues
        extra_backlog = [
            (153, 'ECOM', 'Implement wishlist feature', 'Story', '#059669', 'Medium', '#0891b2', 5, 'OB', None, 'backlog', None, 11, ['feature', 'frontend'], '', ''),
            (154, 'ECOM', 'Add product reviews', 'Story', '#059669', 'Low', '#4f46e5', 3, 'SC', None, 'backlog', None, 12, ['feature'], '', ''),
            (155, 'ECOM', 'SEO optimization', 'Task', '#4f46e5', 'Medium', '#0891b2', 2, 'MJ', None, 'backlog', None, 13, ['seo', 'marketing'], '', ''),
            (156, 'ECOM', 'Promo code engine', 'Epic', '#7c3aed', 'High', '#d97706', 13, None, None, 'backlog', None, 14, ['epic', 'backend'], '', ''),
            (157, 'ECOM', 'International shipping config', 'Task', '#4f46e5', 'Low', '#4f46e5', 3, None, None, 'backlog', None, 15, ['shipping'], '', ''),
        ]
        for (num, proj, title, itype, tcolor, prio, pcolor, pts, assignee,
             due, status, sprint_num, pos, labels, desc, criteria) in extra_backlog:
            db.session.add(Issue(
                project_id=projects[proj].id, number=num, title=title, issue_type=itype,
                type_color=tcolor, priority=prio, priority_color=pcolor, points=pts,
                assignee_id=users[assignee].id if assignee else None,
                assignee_initials=assignee, assignee_color=users[assignee].color if assignee else '#9ca3af',
                due_date=due, labels=labels, status=status, position=pos,
                description=desc, acceptance_criteria=criteria, reporter_id=users['AM'].id,
                sprint_id=sprints[sprint_num].id if sprint_num else None,
            ))

        # ----------------------------------------------------------
        # COMMENTS
        # ----------------------------------------------------------
        comments_data = [
            (148, 'DK', 'Reproduced this on staging. The expiry field misses the on-submit validation check.'),
            (148, 'SC', 'I can pair on this after the checkout API review. Adding a form-level validator should fix it.'),
            (142, 'MJ', 'The endpoint contracts are in the shared OpenAPI spec — make sure you reject cart mutations after checkout has started.'),
        ]
        for issue_num, author, body in comments_data:
            issue = Issue.query.filter_by(number=issue_num, project_id=projects['ECOM'].id).first()
            db.session.add(Comment(issue_id=issue.id, author_id=users[author].id, body=body))

        # ----------------------------------------------------------
        # ACTIVITY
        # ----------------------------------------------------------
        activities = [
            ('plus', '#4f46e5', 'Sarah Chen created ECOM-148', 'Payment validation error', '2h ago'),
            ('user', '#0891b2', 'Alex Morgan assigned ECOM-142 to Sarah Chen', 'Implement checkout API', '4h ago'),
            ('comment', '#059669', 'David Kim commented on ECOM-148', 'Fix confirmed in staging build', '5h ago'),
            ('arrow', '#d97706', 'ECOM-144 moved to In Review', 'Fix cart quantity bug', '8h ago'),
            ('flag', '#7c3aed', 'Sprint 11 completed successfully', '58 points delivered', '1d ago'),
            ('check', '#059669', 'ECOM-150 marked as Done', 'Set up CI pipeline', '1d ago'),
        ]
        for icon, color, text, detail, t in activities:
            db.session.add(Activity(icon=icon, color=color, text=text, detail=detail, time=t))

        # ----------------------------------------------------------
        # NOTIFICATIONS
        # ----------------------------------------------------------
        notifications = [
            ('user', '#4f46e5', 'Sarah assigned ECOM-142 to you.', 'Implement checkout API · High priority', '2h ago', 'assigned', True),
            ('arrow', '#0891b2', 'Payment API moved to In Review.', 'ECOM-148 · Payment validation error', '3h ago', 'updates', True),
            ('alert', '#d97706', 'Sprint 12 ends in 2 days.', '72% complete · 12 tasks in progress', '5h ago', 'updates', True),
            ('at', '#059669', 'You were mentioned in ECOM-145.', 'Alex Morgan: "Can you review the order tracking flow?"', '1d ago', 'mentions', True),
            ('check', '#059669', 'ECOM-150 completed.', 'Set up CI pipeline', '1d ago', 'updates', False),
            ('user', '#4f46e5', 'Priya commented on your task.', 'ECOM-143 · Design looks great!', '2d ago', 'mentions', False),
        ]
        for icon, color, title, detail, t, ntype, unread in notifications:
            db.session.add(Notification(icon=icon, color=color, title=title, detail=detail,
                                        created_at=t, notification_type=ntype, is_read=not unread))

        db.session.commit()
        print('Seed complete. Tables created and populated in:', os.getenv('DATABASE_URL'))


if __name__ == '__main__':
    seed()