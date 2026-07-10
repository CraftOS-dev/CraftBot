# Design Self-Review (Phase 10, Step 1)

Run this BEFORE `living_ui_validate` — look at your own app first.

> Validation ALSO reviews this screenshot itself (`design.judgment` step):
> the platform VLM judges whether the resting page reads as a designed
> application — unfinished-looking layouts (content welded into a corner
> over a void, stray unstructured fragments) are REFUSED with specific
> reasons. Deliberate minimalism and full-bleed layouts pass. Doing this
> self-review first means you never lose a validation run to it.
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
of a web app. Your job is to find ALL UI/UX DEFECTS — things a user would object 
to because they look broken, unfinished, ugly or make the app hard to use. 
Look out for:
text clipped, cut off, or overlapping; elements colliding or misaligned;
misalignment, sections that render as raw/unstyled/broken; text unreadable
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
"fix" things it explicitly identified as plausible design choices.
Be as strict as possible BUT do not nit pick. It is possible that
agent might waste tokens on repeating validation that has already been
fixed. You must compare past design reviews to check if something is fixed, 
as the design review step has no past memory.

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
