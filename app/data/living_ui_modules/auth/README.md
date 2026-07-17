# Auth Module — Multi-User Support for Living UI (PocketBase-native)

Authentication built on PocketBase's built-in auth: email/password accounts,
persistent tokens, role-based access, memberships, and invite codes. No
external services, no hand-written auth backend — PocketBase provides
registration, login, token refresh, and password change out of the box; this
module adds the schema pattern, access rules, hooks, and React components.

## Features
- User registration and login (email + password) — PocketBase native
- First registered user automatically becomes admin (pb_hooks)
- Session persists across reloads (SDK token store + authRefresh)
- Role-based access (admin, member) enforced by collection API rules
- Memberships (link users to any resource) and invite codes
- Pre-built React components on the vendored shadcn/ui kit:
  LoginPage, RegisterPage, UserMenu, ProfilePage, MemberList, InviteModal

## Integration Steps

### 1. Schema

Merge the collections from `schema.auth.json` into the app's
`config/schema.json` `collections` array. Notes:

- `users` is PocketBase's built-in auth collection — declaring it here
  ADDS the `name` and `role` fields and sets the access rules (import
  merges by collection name; nothing is recreated).
- Every rule is explicit. The platform only forces PUBLIC rules where a
  rule is unset, so these auth-gated rules survive import as written.
- Key rules:
  - anyone can register (`createRule: ""` on users);
  - users can update themselves but NOT their own `role`; only an admin
    can change roles or delete accounts;
  - memberships can only be created for yourself (join), removed by
    yourself (leave) or an admin; invites only by their creator or admin.

### 2. Hooks

Copy `pb_hooks/auth.pb.js` into the app's `pb_hooks/` directory. It adds:
- first-user-becomes-admin on registration;
- `POST /api/custom/invites/accept {"code": "..."}` — validates the code
  (expiry, max uses) and creates the membership server-side, so clients
  cannot forge memberships for other users.

### 3. Frontend

Copy the `frontend/*.tsx` files into `frontend/components/auth/`. They
import the template's `@/lib/pb` singleton and `@/components/ui/*`
(shadcn) — no new dependencies.

Gate the app in `App.tsx`:

```tsx
import { useState } from 'react'
import { AuthProvider, useAuth } from './components/auth/AuthProvider'
import { LoginPage } from './components/auth/LoginPage'
import { RegisterPage } from './components/auth/RegisterPage'

function AuthGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  const [page, setPage] = useState<'login' | 'register'>('login')

  if (loading) return null
  if (!isAuthenticated) {
    return page === 'login'
      ? <LoginPage onSwitchToRegister={() => setPage('register')} />
      : <RegisterPage onSwitchToLogin={() => setPage('login')} />
  }
  return <>{children}</>
}

// In App: <AuthProvider><AuthGate><MainView /></AuthGate></AuthProvider>
```

Add `<UserMenu />` to the app header (accepts an optional `onOpenProfile`
callback that can open `<ProfilePage />`).

### 4. Per-user data

Give per-user collections an `owner` relation field and ownership rules in
`config/schema.json`:

```json
{
  "name": "notes",
  "fields": [
    { "name": "title", "type": "text", "required": true },
    { "name": "owner", "type": "relation", "collectionName": "users",
      "required": true, "cascadeDelete": true, "maxSelect": 1 }
  ],
  "listRule": "owner = @request.auth.id",
  "viewRule": "owner = @request.auth.id",
  "createRule": "@request.auth.id != \"\" && owner = @request.auth.id",
  "updateRule": "owner = @request.auth.id",
  "deleteRule": "owner = @request.auth.id"
}
```

PocketBase enforces these on every CRUD and realtime call — no query
filtering code needed. Set `owner: pb.authStore.record?.id` on create.

### 5. Shared resources (memberships)

For resources shared between users (boards, projects, teams), create a
membership when the resource is created:

```ts
const board = await pb.collection('boards').create({ name })
await pb.collection('memberships').create({
  user: pb.authStore.record!.id,
  resourceType: 'board',
  resourceId: board.id,
  role: 'owner',
})
```

List only what the user belongs to by querying memberships first, and rule
the resource collection with a back-relation:

```
listRule: "@collection.memberships.resourceId ?= id &&
           @collection.memberships.user ?= @request.auth.id"
```

Show `<MemberList resourceType="board" resourceId={board.id} />` in the
resource's settings; `<InviteModal ... />` creates and accepts invite codes.

## API surface (all PocketBase-native unless noted)

| Operation | Call |
|---|---|
| Register | `pb.collection('users').create({email, password, passwordConfirm, name})` |
| Login | `pb.collection('users').authWithPassword(email, password)` |
| Current user | `pb.authStore.record` (kept fresh by `AuthProvider`) |
| Update profile | `pb.collection('users').update(id, {name})` |
| Change password | `pb.collection('users').update(id, {oldPassword, password, passwordConfirm})` |
| Logout | `pb.authStore.clear()` |
| List users (auth'd) | `pb.collection('users').getFullList()` |
| Members of a resource | `pb.collection('memberships').getFullList({filter, expand: 'user'})` |
| Create invite | `pb.collection('invites').create({...})` |
| Accept invite | `POST /api/custom/invites/accept {"code"}` (pb_hooks — the one custom endpoint) |
