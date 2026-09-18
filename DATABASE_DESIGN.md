# Database Design

## Overview

This project uses **Flask-SQLAlchemy** with SQLite. The database schema is defined in `models.py`.

## Entity Relationship Diagram

```
┌─────────────┐       ┌─────────────────┐       ┌─────────────┐
│    Users     │       │ ProjectMembers   │       │  Projects   │
├─────────────┤       ├─────────────────┤       ├─────────────┤
│ id (PK)     │◄──┐   │ id (PK)         │   ┌──►│ id (PK)     │
│ name        │   └───│ user_id (FK)    │   │   │ key         │
│ initials    │       │ project_id (FK) │───┘   │ name        │
│ email       │       └─────────────────┘       │ description │
│ password    │                                 │ lead_id(FK) │
│ plan        │       ┌─────────────────┐       │ status      │
│ role        │       │   Sprints       │       └─────────────┘
│ team        │       ├─────────────────┤             │
│ ...         │       │ id (PK)         │             │
└─────────────┘       │ project_id (FK) │◄────────────┘
      │               │ number          │
      │               │ name            │
      │               │ status          │
      │               └─────────────────┘
      │                       │
      │               ┌─────────────────┐
      │               │    Issues        │
      │               ├─────────────────┤
      └──────────────►│ id (PK)         │
                      │ project_id (FK) │
                      │ sprint_id (FK)  │
                      │ assignee_id(FK) │
                      │ reporter_id(FK) │
                      │ number          │
                      │ title           │
                      │ status          │
                      │ priority        │
                      │ points          │
                      └─────────────────┘
                             │
                      ┌─────────────────┐
                      │   Comments      │
                      ├─────────────────┤
                      │ id (PK)         │
                      │ issue_id (FK)   │
                      │ author_id (FK)  │
                      │ body            │
                      └─────────────────┘
```

## Tables

### Users

Stores user accounts and profile information.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique user identifier |
| name | VARCHAR(120) | NOT NULL | Full name |
| initials | VARCHAR(8) | NOT NULL | Display initials (e.g., "JD") |
| email | VARCHAR(180) | UNIQUE, NOT NULL | Login email |
| password_hash | VARCHAR(256) | NOT NULL | Hashed password |
| plan | VARCHAR(20) | NOT NULL, DEFAULT 'lite' | Subscription plan (lite/pro) |
| role | VARCHAR(80) | NOT NULL | Job role |
| permission_role | VARCHAR(40) | NOT NULL, DEFAULT 'member' | Permission level |
| team | VARCHAR(80) | NOT NULL | Team assignment |
| capacity | INTEGER | DEFAULT 70 | Work capacity percentage |
| active_projects | INTEGER | DEFAULT 1 | Number of active projects |
| current_tasks | INTEGER | DEFAULT 0 | Current task count |
| color | VARCHAR(20) | DEFAULT '#4f46e5' | Avatar color |
| status | VARCHAR(40) | DEFAULT 'Active' | Account status |
| last_seen | DATETIME | NULLABLE | Last activity timestamp |
| created_at | DATETIME | NULLABLE | Account creation date |
| updated_at | DATETIME | NULLABLE | Last update timestamp |

---

### Projects

Project container for organizing issues and sprints.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique project identifier |
| key | VARCHAR(12) | UNIQUE, NOT NULL | Project key (e.g., "ECOM") |
| name | VARCHAR(160) | NOT NULL | Project name |
| description | TEXT | DEFAULT '' | Project description |
| lead_id | INTEGER | FK → users.id | Project lead |
| lead_initials | VARCHAR(8) | | Lead's initials |
| color | VARCHAR(20) | DEFAULT '#4f46e5' | Project color |
| status | VARCHAR(40) | DEFAULT 'In Progress' | Project status |
| start_date | VARCHAR(40) | | Start date |
| due_date | VARCHAR(40) | | Target completion date |
| progress | INTEGER | DEFAULT 0 | Completion percentage |
| health_schedule | VARCHAR(40) | DEFAULT 'On Track' | Schedule health |
| health_budget | VARCHAR(40) | DEFAULT 'On Track' | Budget health |
| health_scope | VARCHAR(40) | DEFAULT 'On Track' | Scope health |
| health_capacity | VARCHAR(40) | DEFAULT 'Good' | Capacity health |

---

### ProjectMembers

Junction table for many-to-many relationship between Users and Projects.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Record identifier |
| project_id | INTEGER | FK → projects.id | Project reference |
| user_id | INTEGER | FK → users.id | User reference |

---

### Sprints

Time-boxed iteration periods within a project.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique sprint identifier |
| number | INTEGER | NOT NULL | Sprint sequence number |
| name | VARCHAR(80) | | Sprint name |
| project_id | INTEGER | FK → projects.id | Parent project |
| start_date | VARCHAR(40) | | Sprint start date |
| end_date | VARCHAR(40) | | Sprint end date |
| goal | VARCHAR(160) | | Sprint goal |
| description | TEXT | DEFAULT '' | Sprint description |
| status | VARCHAR(40) | DEFAULT 'Planned' | Status (Planned/Active/Closed) |
| to_do | INTEGER | DEFAULT 0 | To-do task count |
| in_progress | INTEGER | DEFAULT 0 | In-progress task count |
| in_review | INTEGER | DEFAULT 0 | In-review task count |
| done | INTEGER | DEFAULT 0 | Completed task count |
| story_points_total | INTEGER | DEFAULT 0 | Total story points |
| story_points_done | INTEGER | DEFAULT 0 | Completed story points |

---

### Issues

Work items (stories, bugs, tasks) within a project.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique issue identifier |
| project_id | INTEGER | FK → projects.id | Parent project |
| number | INTEGER | | Issue number within project |
| title | VARCHAR(240) | NOT NULL | Issue title |
| issue_type | VARCHAR(40) | DEFAULT 'Story' | Type (Story/Bug/Task/Epic) |
| type_color | VARCHAR(20) | DEFAULT '#4f46e5' | Type badge color |
| priority | VARCHAR(20) | DEFAULT 'Medium' | Priority level |
| priority_color | VARCHAR(20) | DEFAULT '#0891b2' | Priority badge color |
| points | INTEGER | DEFAULT 0 | Story points |
| assignee_id | INTEGER | FK → users.id | Primary assignee |
| assignee_initials | VARCHAR(8) | | Assignee initials |
| assignee_color | VARCHAR(20) | DEFAULT '#4f46e5' | Assignee avatar color |
| due_date | VARCHAR(40) | | Target completion date |
| start_date | VARCHAR(40) | | Work start date |
| labels | JSON | DEFAULT [] | Issue labels |
| status | VARCHAR(40) | DEFAULT 'backlog' | Status (backlog/todo/in_progress/in_review/done) |
| position | INTEGER | DEFAULT 0 | Sort order |
| description | TEXT | DEFAULT '' | Issue description |
| acceptance_criteria | TEXT | DEFAULT '' | Acceptance criteria |
| reporter_id | INTEGER | FK → users.id | Issue creator |
| sprint_id | INTEGER | FK → sprints.id | Assigned sprint |
| created_at | VARCHAR(40) | | Creation timestamp |
| completed_at | DATETIME | NULLABLE | Completion timestamp |

---

### IssueAssignees

Junction table for multiple assignees on a single issue.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Record identifier |
| issue_id | INTEGER | FK → issues.id | Issue reference |
| user_id | INTEGER | FK → users.id | User reference |

---

### Comments

Discussion threads on issues.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique comment identifier |
| issue_id | INTEGER | FK → issues.id | Parent issue |
| author_id | INTEGER | FK → users.id | Comment author |
| body | TEXT | NOT NULL | Comment content |
| created_at | VARCHAR(40) | | Creation timestamp |

---

### Activities

Audit log for system events.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique activity identifier |
| icon | VARCHAR(20) | DEFAULT 'plus' | Display icon |
| color | VARCHAR(20) | DEFAULT '#4f46e5' | Display color |
| text | VARCHAR(240) | | Activity description |
| detail | VARCHAR(240) | | Additional details |
| time | VARCHAR(40) | | Activity timestamp |

---

### Notifications

User notification queue with filtering support.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, Auto-increment | Unique notification identifier |
| icon | VARCHAR(20) | DEFAULT 'bell' | Display icon |
| color | VARCHAR(20) | DEFAULT '#4f46e5' | Display color |
| title | VARCHAR(240) | | Notification title |
| detail | VARCHAR(240) | | Additional details |
| message | TEXT | DEFAULT '' | Notification message |
| notification_type | VARCHAR(20) | DEFAULT 'updates' | Type category |
| is_read | BOOLEAN | DEFAULT FALSE | Read status |
| created_at | VARCHAR(40) | | Creation timestamp |
| created_dt | DATETIME | | Creation datetime (for queries) |
| type | VARCHAR(40) | DEFAULT 'system' | Event type |
| category | VARCHAR(20) | DEFAULT 'updates' | Category (assigned/mentions/updates) |
| priority | VARCHAR(20) | DEFAULT 'normal' | Priority (normal/important/urgent) |
| recipient_id | INTEGER | FK → users.id, INDEXED | Notification recipient |
| actor_id | INTEGER | FK → users.id | User who triggered event |
| project_id | INTEGER | FK → projects.id | Related project |
| issue_id | INTEGER | FK → issues.id | Related issue |
| sprint_id | INTEGER | FK → sprints.id | Related sprint |
| event_key | VARCHAR(200) | UNIQUE, INDEXED | Deduplication key |
| meta | JSON | NULLABLE | Additional metadata |
| read_at | DATETIME | NULLABLE | Read timestamp |
| deleted_at | DATETIME | NULLABLE | Soft delete timestamp |

**Indexes:**
- `ix_notif_recipient_read` on (recipient_id, is_read)
- `ix_notif_recipient_created` on (recipient_id, created_dt)
- `ix_notif_recipient_category` on (recipient_id, category)

---

### WorkspaceSettings

Singleton table for workspace-level configuration.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK | Always 1 |
| name | VARCHAR(160) | NOT NULL, DEFAULT 'ABC' | Workspace name |
| slug | VARCHAR(80) | UNIQUE, NOT NULL | URL-friendly identifier |
| domain | VARCHAR(120) | DEFAULT '' | Company domain |
| logo_path | VARCHAR(240) | DEFAULT '' | Logo file path |
| logo_color | VARCHAR(20) | DEFAULT '#4f46e5' | Logo accent color |
| description | TEXT | DEFAULT '' | Workspace description |
| default_issue_type | VARCHAR(40) | DEFAULT 'Story' | Default new issue type |
| default_priority | VARCHAR(20) | DEFAULT 'Medium' | Default issue priority |
| default_status | VARCHAR(20) | DEFAULT 'todo' | Default issue status |
| default_project_visibility | VARCHAR(20) | DEFAULT 'private' | Default project visibility |
| timezone | VARCHAR(40) | DEFAULT 'UTC-5 (Eastern)' | Workspace timezone |
| date_format | VARCHAR(20) | DEFAULT '%b %d, %Y' | Date display format |
| working_days | JSON | DEFAULT ['Mon','Tue','Wed','Thu','Fri'] | Working days |
| created_at | DATETIME | NULLABLE | Creation timestamp |
| updated_at | DATETIME | NULLABLE | Last update timestamp |

---

### UserNotificationPreferences

Per-user notification settings.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| user_id | INTEGER | PK, FK → users.id | User reference |
| mentions | BOOLEAN | DEFAULT TRUE | Mention notifications |
| assignments | BOOLEAN | DEFAULT TRUE | Assignment notifications |
| status_changes | BOOLEAN | DEFAULT TRUE | Status change notifications |
| comments | BOOLEAN | DEFAULT TRUE | Comment notifications |
| sprint_updates | BOOLEAN | DEFAULT TRUE | Sprint update notifications |
| due_date_reminders | BOOLEAN | DEFAULT TRUE | Due date reminders |
| overdue | BOOLEAN | DEFAULT TRUE | Overdue notifications |
| project_updates | BOOLEAN | DEFAULT TRUE | Project update notifications |
| system | BOOLEAN | DEFAULT TRUE | System notifications |
| created_at | DATETIME | NULLABLE | Creation timestamp |
| updated_at | DATETIME | NULLABLE | Last update timestamp |

---

## Relationships

| From | To | Type | Description |
|------|-----|------|-------------|
| Projects.lead_id | Users.id | Many-to-One | Project has one lead |
| ProjectMembers.project_id | Projects.id | Many-to-One | Member belongs to project |
| ProjectMembers.user_id | Users.id | Many-to-One | Member is a user |
| Sprints.project_id | Projects.id | Many-to-One | Sprint belongs to project |
| Issues.project_id | Projects.id | Many-to-One | Issue belongs to project |
| Issues.sprint_id | Sprints.id | Many-to-One | Issue belongs to sprint |
| Issues.assignee_id | Users.id | Many-to-One | Issue has primary assignee |
| Issues.reporter_id | Users.id | Many-to-One | Issue created by user |
| IssueAssignees.issue_id | Issues.id | Many-to-One | Assignee link to issue |
| IssueAssignees.user_id | Users.id | Many-to-One | Assignee link to user |
| Comments.issue_id | Issues.id | Many-to-One | Comment on issue |
| Comments.author_id | Users.id | Many-to-One | Comment by user |
| Notifications.recipient_id | Users.id | Many-to-One | Notification for user |
| Notifications.actor_id | Users.id | Many-to-One | Notification triggered by user |
| Notifications.project_id | Projects.id | Many-to-One | Notification about project |
| Notifications.issue_id | Issues.id | Many-to-One | Notification about issue |
| Notifications.sprint_id | Sprints.id | Many-to-One | Notification about sprint |
| UserNotificationPreferences.user_id | Users.id | One-to-One | User's notification prefs |

---

## Status Enums

### Issue Status
- `backlog`
- `todo`
- `in_progress`
- `in_review`
- `done`

### Sprint Status
- `Planned`
- `Active`
- `Closed`

### Project Status
- `Planning`
- `In Progress`
- `On Hold`
- `Completed`

### Issue Types
- `Story`
- `Bug`
- `Task`
- `Epic`

### Priority Levels
- `Highest`
- `High`
- `Medium`
- `Low`
- `Lowest`
- `Critical`

---

## Seed Data

Default data is seeded via `seed.py`. Run with:

```bash
python seed.py
```
