# Agent App Requirement Questionnaire

Reference guide for gathering requirements before building a Agent App.
The agent should NOT ask all questions — select the most relevant ones
based on the project description and ask in batches of 2-4.

## How to Use This Guide

1. Read the project description carefully
2. Identify which categories below are ambiguous or underspecified
3. Pick 2-4 questions per batch from the most relevant categories
4. Skip categories where the description already provides clear answers
5. Fill gaps with reasonable assumptions and state them explicitly
6. Maximum 2-3 batches total — don't over-interview

## Category 1: Design & Visual Identity

- What color scheme do you prefer? (e.g., specific brand colors, or a mood like "clean and minimal", "dark and techy", "warm and friendly")
- Light theme, dark theme, or follow system preference?
- Any layout style preference? (dashboard with panels, kanban board, list/table view, freeform canvas, card grid)
- Any visual style preferences? (modern/minimal, playful, corporate, retro)
- Should it match an existing brand or tool's look?

## Category 2: Data & Entities

- What are the main "things" in your app? (e.g., tasks, notes, projects, contacts, items)
- What information does each thing have? (e.g., a task has title, description, due date, priority, status)
- How do these things relate to each other? (e.g., a project has many tasks, a board has many cards)
- Do you need categories, tags, or labels to organize items?
- Should items have statuses or workflows? (e.g., idea → in progress → done)

## Category 3: Features & Functionality

- What operations matter most? (create, view, edit, delete — all? or mainly viewing?)
- Do you need search or filtering? By what fields?
- Do you need sorting? By what criteria?
- Should items support media? (images, videos, YouTube embeds, file links, documents)
- Do you need detail/expanded views when clicking an item?
- Should items be reorderable or have drag-and-drop?
- Do you need any bulk operations? (multi-select, batch delete)

## Category 4: Layout & Navigation

- Single page or multi-page/tabbed?
- Do you need a sidebar, top nav, or minimal navigation?
- How should the main content be organized? (grid, list, columns, freeform)
- Detail panel on the side (click item → see details) or modal-based detail views?

## Category 5: UX & Polish

- What should empty states look like? (helpful message + action button, or minimal?)
- How important is mobile responsiveness? (primary mobile use, desktop-first, or both equally?)
- Any specific interactions? (hover previews, inline editing, keyboard shortcuts)

## Category 6: Users & Access

- Will multiple people use this app, each with their own data?
- Do you need user accounts (login/register)?
- Should some users have admin privileges?
- Do users need to collaborate or share data?

## Expanding Vague Answers

When the user gives a brief or vague reply, expand it into specific features and **confirm with the user** before documenting in AGENT_APP.md.

### Common Expansions

| User says | Expand to |
|-----------|-----------|
| "basic user stuff" / "user management" | Login, signup, user profiles, member list, role-based access (admin/member), password change |
| "normal layout" / "standard layout" | Left sidebar for navigation, main content area, responsive, top header with app name + user menu |
| "simple dashboard" / "basic dashboard" | Stat cards (3-4 key metrics), recent activity list, quick-action buttons |
| "basic CRUD" / "the usual" | Create, read, update, delete with confirmation dialogs, search/filter, sort by date |
| "make it look good" / "clean design" | Modern minimal style, system theme (light/dark), CraftBot design tokens, card-based layout, no gradients |
| "basic settings" / "settings page" | User profile edit, theme toggle, notification preferences, account deletion |
| "notifications" / "alerts" | Toast notifications for CRUD feedback, email-style notification center for async events |
| "basic search" / "search" | Text search across primary fields, filter dropdowns for status/category/tags, clear filters button |
| "drag and drop" | Reorderable items via drag, column-to-column for kanban, visual drop indicator |
| "sharing" / "collaboration" | Membership system (invite by code), per-resource access control, member list, owner/admin/member roles |
| "comments" | Per-item comment thread, author + timestamp, no threading (flat), delete own comments |
| "tags" / "labels" | Colored tag chips, create/delete tags, filter by tag, multi-tag per item |
| "calendar view" | Monthly grid showing items by due date, click to view/edit, overdue highlighting |
| "dark mode" | System theme preference toggle (light/dark/auto), persisted in localStorage |

### How to Confirm

After expanding, confirm with the user in a natural way:

> "Got it! By 'basic user stuff' I'll set up:
> - Login & signup (email + password)
> - User profiles (edit name, email, change password)
> - Member list (see who's in the project)
> - Roles: admin (manage everything) and member (standard access)
>
> Sound right, or would you add/remove anything?"

**Never proceed with vague answers as-is.** Always expand, always confirm.

## Safe Assumptions

The agent can assume the following unless the user says otherwise:

- System theme preference (follows OS light/dark setting)
- Responsive design (works on mobile and desktop)
- Standard CRUD for all entities (create, read, update, delete)
- Loading spinners for async operations
- Confirmation dialogs for destructive actions (delete)
- Empty states with helpful messages and action buttons
- Clean, modern visual style using CraftBot design tokens
- Search/filter on primary text fields
- Items sorted by creation date (newest first) by default
