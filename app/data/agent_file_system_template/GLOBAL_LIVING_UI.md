# Global Living UI Configuration

Global design preferences and rules applied to ALL Living UI projects.
Per-project settings from Phase 0 Q&A override these when they conflict.

## Design Preferences

- **Primary Color:** #FF4F18
- **Secondary Color:** #262626
- **Accent Color:** #E64515
- **Background Style:** Default (use CraftBot design tokens)
- **Theme Mode:** Follow system (dark/light)
- **Font Family:** System default (Segoe UI, sans-serif)
- **Border Radius:** Rounded (var(--radius-md))
- **Spacing:** Comfortable

## Always Enforced

- Must use preset UI components (Button, Card, Input, Modal, Table, etc.)
- Must use design tokens from global.css (no arbitrary colors)
- All API calls must handle errors with user-visible feedback
- No inline styles for standard UI elements
- Use react-toastify for notifications (already installed)
- Backend routes must use absolute imports (not relative)
- Images must always render with visible thumbnails
- Videos must show preview thumbnails
- Links should show preview cards when possible
- Empty states must have helpful messages with action buttons
- Loading spinners required for all async operations
- Use toast notifications for all CRUD feedback (success, error)
- Show confirmation dialogs for destructive actions (delete, reset)
- Forms must have inline validation with error messages
- Mobile responsive design required
- Hover states on all clickable elements
- Text must have sufficient contrast against background (dark text on light backgrounds, light text on dark backgrounds)
- Never use light text on light backgrounds or dark text on dark backgrounds

## Custom Rules

<!-- Add your own rules below as bullet lines -->
<!-- Example: - All lists must support search/filter -->
- Enable drag-and-drop for reordering items
- Add keyboard shortcuts for common actions
- Show item count badges on categories/sections
- Add search/filter bar to all list views
- Support bulk selection and batch operations
- Add animations and transitions to UI interactions
- Add undo/redo support for user actions
