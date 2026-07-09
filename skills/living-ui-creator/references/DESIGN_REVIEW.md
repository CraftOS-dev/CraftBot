# Design Self-Review (Phase 10, Step 1)

Run this BEFORE `living_ui_validate` — look at your own app first.
Use the describe_image call below with the prompt EXACTLY as written
(it encodes the defect-vs-design-decision distinction; ad-libbed
prompts produce false failures).

While you build, the live preview continuously saves a screenshot of your
app to `{project_path}/logs/design_preview.png`. LOOK at it before you
spend a validation run:

```
describe_image(
  image_path="{project_path}/logs/design_preview.png",
  prompt="You are an experienced UI/UX design reviewer looking at a screenshot
of a web app that was JUST BUILT and has NO USER DATA YET. Your job is to
find UI/UX DEFECTS — things a user would object to because
they look broken, unfinished, or make the app hard to use — while
respecting INTENTIONAL DESIGN DECISIONS. Before flagging anything, ask:
'is this a bug, or is this a choice a competent designer plausibly made
on purpose?' Conventional design patterns (visual hierarchy through
muted/secondary styling, whitespace as breathing room, empty states in an
app that has no data yet, restrained color palettes, de-emphasized
metadata) are NOT defects. A region that is empty because the app is
waiting for user content is fine IF it communicates that state; it is a
defect only if it renders as broken or unexplained dead space. DO report:
text clipped, cut off, or overlapping; elements colliding or misaligned;
sections that render as raw/unstyled/broken; text unreadable
against its background; controls that look unfinished or misplaced;
inconsistency between elements that should look alike; a UI that reads as
an unstyled wall of text with no visual structure, icons, or accents for
its scope. For each defect: say WHERE it is, WHY it is a defect rather
than a plausible design choice, and what a user would complain about.
Verdict: PASS unless there are genuine defects — do not fail the app for
defensible design decisions or for the absence of data it doesn't have
yet."
)
```

If the review lists a genuine defect: fix the layout/CSS/visual design,
wait a moment for the preview screenshot to refresh, and re-review. Repeat
until PASS. Trust the reviewer's decision/defect distinction — do not
"fix" things it explicitly identified as plausible design choices. If
`design_preview.png` does not exist (preview never open), skip this step —
the platform's design gate still applies.

## Runtime-Log Check (same step, after the visual review)

The platform records the app's runtime behavior; read BOTH before
validating and treat every ERROR entry as a defect to fix:

- `{project_path}/backend/logs/frontend_console.log` — runtime crashes,
  unhandled rejections, failed requests captured from the live preview
- the newest `{project_path}/backend/logs/backend_*.log` — unhandled
  500s and tracebacks

Validation runs the same check (step `runtime.logs`) over the validation
window and REFUSES on recorded errors — finding them yourself first is
cheaper.
