/// <reference path="../pb_data/types.d.ts" />
/**
 * Auth module hooks — copy into the app's pb_hooks/ directory.
 *
 * Adds the two pieces PocketBase's built-in auth does not cover:
 * 1. First registered user becomes admin (everyone after: member).
 * 2. Invite-code acceptance (validates the code server-side and creates
 *    the membership — clients cannot forge memberships for other users).
 */

// First user = admin. Runs on the registration request, before save.
onRecordCreateRequest((e) => {
  let isFirst = false
  try {
    isFirst = $app.countRecords("users") === 0
  } catch (_) {
    /* fail-open: default role below still applies */
  }
  if (isFirst) {
    e.record.set("role", "admin")
  } else if (!e.record.get("role")) {
    e.record.set("role", "member")
  }
  e.next()
}, "users")

// Accept an invite code: POST /api/custom/invites/accept {"code": "..."}
// Joins the signed-in user to the invite's resource with the invite's role.
routerAdd("POST", "/api/custom/invites/accept", (e) => {
  const auth = e.auth
  if (!auth || !auth.id) {
    return e.json(401, { error: "Sign in to accept an invite" })
  }
  const body = e.requestInfo().body || {}
  const code = String(body.code || "").trim()
  if (!code) {
    return e.json(400, { error: "Missing invite code" })
  }

  let invite
  try {
    invite = $app.findFirstRecordByFilter("invites", "code = {:code}", {
      code: code,
    })
  } catch (_) {
    return e.json(404, { error: "Invalid invite code" })
  }

  const expiresAt = invite.get("expiresAt")
  if (expiresAt && new Date(expiresAt) < new Date()) {
    return e.json(410, { error: "This invite has expired" })
  }
  const maxUses = invite.get("maxUses") || 0
  const uses = invite.get("uses") || 0
  if (maxUses > 0 && uses >= maxUses) {
    return e.json(410, { error: "This invite has no uses left" })
  }

  // Already a member? Idempotent success.
  const existing = $app.findRecordsByFilter(
    "memberships",
    "user = {:user} && resourceType = {:rt} && resourceId = {:rid}",
    "",
    1,
    0,
    { user: auth.id, rt: invite.get("resourceType"), rid: invite.get("resourceId") }
  )
  if (existing.length > 0) {
    return e.json(200, { status: "already-member" })
  }

  const col = $app.findCollectionByNameOrId("memberships")
  const membership = new Record(col)
  membership.set("user", auth.id)
  membership.set("resourceType", invite.get("resourceType"))
  membership.set("resourceId", invite.get("resourceId"))
  membership.set("role", invite.get("role") || "member")
  $app.save(membership)

  invite.set("uses", uses + 1)
  $app.save(invite)

  return e.json(200, {
    status: "joined",
    resourceType: invite.get("resourceType"),
    resourceId: invite.get("resourceId"),
  })
})
