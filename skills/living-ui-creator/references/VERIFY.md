# Living UI Verification Checklist

**You are a strict product manager.** Before marking any Living UI as complete, you MUST verify every item on this checklist. Do not skip any section. If any check fails, fix it before proceeding.

## 1. Build Verification

### 1.1 Backend Compiles
```bash
cd backend && python -c "from models import *; from routes import *; print('Backend OK')"
```
- [ ] Command exits with code 0
- [ ] No import errors
- [ ] No syntax errors

### 1.2 Frontend Builds
```bash
npm run build
```
- [ ] Command exits with **code 0** (not just "ran")
- [ ] No TypeScript errors
- [ ] No compilation warnings that indicate bugs
- [ ] `dist/` folder is created

**If build fails:** Read the error message carefully. Fix ALL errors. Rebuild. Repeat until success.

## 2. Functional Verification

### 2.1 Core Features Work
For each feature the user requested, verify:
- [ ] Feature can be triggered (button click, form submit, etc.)
- [ ] Feature produces expected result
- [ ] Result is visible in the UI
- [ ] Result persists after page refresh

### 2.2 CRUD Operations (if applicable)
- [ ] **Create**: Can add new items
- [ ] **Read**: Items display correctly
- [ ] **Update**: Can modify existing items
- [ ] **Delete**: Can remove items
- [ ] All operations reflect immediately in UI

### 2.3 State Persistence
This is **critical**. Test this flow:
1. Perform some actions (add items, change values, etc.)
2. Refresh the browser page
3. Verify ALL changes are still there

- [ ] State survives page refresh
- [ ] State survives closing and reopening the tab
- [ ] No data loss occurs

**If state is lost:** Your backend integration is broken. Check:
- Is AppController calling backend APIs?
- Are routes saving to database?
- Is `db.commit()` being called?

## 3. UI/UX Verification

### 3.1 Visual Quality
- [ ] Layout is clean and organized
- [ ] Text is readable (appropriate font size, contrast)
- [ ] Spacing is consistent (no cramped or floating elements)
- [ ] Colors are harmonious (not jarring or clashing)
- [ ] No obvious visual bugs (overflow, misalignment)

### 3.2 Visual Consistency
- [ ] Same element types look the same everywhere (buttons, inputs, cards)
- [ ] Consistent padding/margins throughout
- [ ] Consistent color scheme
- [ ] Consistent typography (font sizes, weights)

### 3.3 Responsive Behavior
- [ ] UI doesn't break at different widths
- [ ] Content doesn't overflow horizontally
- [ ] Buttons and inputs are usable at all sizes

### 3.4 Loading & Empty States
- [ ] Loading indicator shows while fetching data
- [ ] Empty state shows when no data exists (not just blank)
- [ ] Error messages display when something fails

### 3.5 Interactive Feedback
- [ ] Buttons show hover/active states
- [ ] Form inputs show focus states
- [ ] Actions provide feedback (success message, visual change)
- [ ] User knows something happened after clicking

## 4. Error Handling Verification

### 4.1 No Console Errors
Open browser dev tools (F12) → Console tab:
- [ ] No red error messages
- [ ] No unhandled promise rejections
- [ ] No "undefined" or "null" errors
- [ ] No CORS errors

### 4.2 Graceful Failures
- [ ] If backend is slow, UI shows loading (not frozen)
- [ ] If an action fails, user sees error message (not silent failure)
- [ ] App doesn't crash on edge cases

## 5. Requirements Verification

### 5.1 Feature Completeness
Go back to the original user request. For EACH requested feature:
- [ ] Feature is implemented
- [ ] Feature works as described
- [ ] Feature is accessible in the UI

### 5.2 Nothing Missing
Ask yourself:
- [ ] Would the user be satisfied with this?
- [ ] Are there obvious features that should exist but don't?
- [ ] Does it do what was asked?

### 5.3 Nothing Extra (Over-engineering)
- [ ] No features added that weren't requested
- [ ] No unnecessary complexity
- [ ] Focused on what was asked

## 6. Code Quality Verification

### 6.1 No Hardcoded Data
- [ ] No hardcoded IDs that should be dynamic
- [ ] No hardcoded URLs (use environment/config)
- [ ] No TODO comments left unaddressed
- [ ] No commented-out code blocks

### 6.2 Type Safety
- [ ] No `any` types in TypeScript (unless absolutely necessary)
- [ ] All function parameters are typed
- [ ] All return types are defined

### 6.3 Backend Quality
- [ ] All routes have proper error handling
- [ ] Database queries use proper filters
- [ ] No SQL injection vulnerabilities
- [ ] Proper HTTP status codes returned

## 7. Documentation Verification

### 7.1 LIVING_UI.md Updated
- [ ] Overview section filled in
- [ ] Data Model section documents all models
- [ ] API Endpoints section lists all routes
- [ ] Frontend Components section lists all components
- [ ] Key Files section is accurate

## 8. Final Pre-Launch Checks

### 8.1 Ready to Notify
Before calling `living_ui_notify_ready`:
- [ ] ALL above sections pass
- [ ] Build succeeded (exit code 0)
- [ ] Tested in browser manually
- [ ] No dev server left running

### 8.2 Correct Parameters
- [ ] `project_id` is from task instruction (NOT task session ID)
- [ ] `port` matches `config/manifest.json`
- [ ] `url` is correctly formatted

---

## Quick Verification Commands

```bash
# 1. Verify backend
cd backend && python -c "from models import *; from routes import *; print('OK')"

# 2. Build frontend
npm run build

# 3. Check build succeeded
echo $?  # Should print 0
```

## Common Issues & Fixes

### Build fails with TypeScript errors
- Read error message for file and line number
- Fix the type error
- Rebuild

### State lost on refresh
- Check AppController.initialize() fetches from backend
- Check routes call db.commit() after changes
- Check models have to_dict() method

### UI looks broken
- Check CSS imports in components
- Check global.css is imported in main.tsx
- Verify class names match CSS

### Console shows CORS errors
- Backend CORS is pre-configured, check main.py
- Ensure frontend uses correct backend URL

---

**Remember: You are the last line of defense before the user sees this app. Be thorough. Be critical. Ship quality.**

---

## 9. CLI Operability (MANDATORY)

The finished app must be fully operable through the `livingui` CLI — this is
how every future agent (and scheduled task) will control it.

Run via run_shell: `livingui <project_id> --help`

- [ ] The capability card lists ALL the app's data tables with row counts
- [ ] Every side-effectful feature appears under OPERATIONS (coverage rule:
      each feature in LIVING_UI.md = a table OR a declared op)
- [ ] `livingui <project_id> run <op> --help` shows correct params for each op
- [ ] Fire ONE representative op end-to-end and confirm the expected effect
      (e.g. `run complete_habit ...` then `select` the row)
- [ ] No "schema drift" warning in the card
- [ ] Op descriptions say when to use them (an agent must be able to choose
      the right op from descriptions alone)

If any box fails, go back to Phase 9 — do not launch a half-operable app.

