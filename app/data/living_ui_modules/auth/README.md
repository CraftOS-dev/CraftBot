# Auth Module — Multi-User Support for Living UI

Self-contained authentication with SQLite + bcrypt + JWT. No external services needed.

## Features
- User registration and login (email + password)
- First user automatically becomes admin
- JWT token auth (24h expiry, stored in localStorage)
- Role-based access (admin, member)
- Pre-built React components (LoginPage, RegisterPage, UserMenu)

## Integration Steps

### Backend

1. Copy these files into `backend/`:
   - `auth_models.py` — User model
   - `auth_service.py` — password hashing + JWT
   - `auth_middleware.py` — FastAPI dependencies (get_current_user, require_admin)
   - `auth_routes.py` — /auth/register, /auth/login, /auth/me, /auth/users

2. Append to `backend/requirements.txt`:
   ```
   bcrypt>=4.0.0
   PyJWT>=2.8.0
   ```

3. In `backend/routes.py`, import and include the auth router:
   ```python
   from auth_routes import router as auth_router
   router.include_router(auth_router)
   ```

4. Import `User` in `routes.py` (NOT models.py — that file is
   system-managed) so the table is created; including the auth router in
   step 3 already does this implicitly:
   ```python
   from auth_models import User  # noqa: F401
   ```

5. Add a `userId` ref-style field to the entities that are per-user in
   `config/schema.json` (an `integer` field holding the user's id):
   ```json
   "userId": {"type": "integer", "required": true}
   ```
   and enforce ownership in your custom routes / queries.

6. Protect routes with auth dependency:
   ```python
   from auth_middleware import get_current_user
   
   @router.get("/my-items")
   def get_my_items(user = Depends(get_current_user), db = Depends(get_db)):
       return db.query(Item).filter(Item.user_id == user.id).all()
   ```

### Frontend

1. Copy `auth_types.ts` into `frontend/`
2. Copy `AuthService.ts` into `frontend/services/`
3. Copy `AuthProvider.tsx`, `LoginPage.tsx`, `RegisterPage.tsx`, `UserMenu.tsx` into `frontend/components/auth/`

4. Wrap your app in AuthProvider (in App.tsx):
   ```tsx
   import { AuthProvider, useAuth } from './components/auth/AuthProvider'
   import { LoginPage } from './components/auth/LoginPage'
   import { RegisterPage } from './components/auth/RegisterPage'
   
   function App() {
     return (
       <AuthProvider>
         <AuthGate />
       </AuthProvider>
     )
   }
   
   function AuthGate() {
     const { isAuthenticated, loading } = useAuth()
     const [page, setPage] = useState<'login' | 'register'>('login')
     
     if (loading) return <div>Loading...</div>
     if (!isAuthenticated) {
       return page === 'login'
         ? <LoginPage onSwitchToRegister={() => setPage('register')} />
         : <RegisterPage onSwitchToLogin={() => setPage('login')} />
     }
     return <MainView />
   }
   ```

5. Add UserMenu to your header:
   ```tsx
   import { UserMenu } from './components/auth/UserMenu'
   
   <header style={{ display: 'flex', justifyContent: 'space-between' }}>
     <h1>My App</h1>
     <UserMenu />
   </header>
   ```

6. Use `authService.authFetch()` instead of `fetch()` for authenticated API calls:
   ```typescript
   import { authService } from './services/AuthService'
   const resp = await authService.authFetch(`${BACKEND_URL}/api/my-items`)
   ```

### Tests

Copy `tests/test_auth.py` into `backend/tests/`. Run:
```
cd backend && python -m pytest tests/test_auth.py -v
```

## Membership — Connecting Users to Resources

The auth module includes a generic **Membership** system for linking users to app resources
(projects, boards, teams, etc.) and an **Invite** system for shareable join links.

### How it works

When a user creates a resource (e.g., a project), also create a Membership:
```python
from auth_models import Membership

@router.post("/projects")
def create_project(data: ..., user = Depends(get_current_user), db = Depends(get_db)):
    project = Project(name=data.name, created_by=user.id)
    db.add(project)
    db.flush()  # Get project.id

    # Make creator the owner
    membership = Membership(user_id=user.id, resource_type="project",
                            resource_id=project.id, role="owner")
    db.add(membership)
    db.commit()
    return project.to_dict()
```

### Filtering by membership

Only show resources the user is a member of:
```python
@router.get("/projects")
def get_my_projects(user = Depends(get_current_user), db = Depends(get_db)):
    project_ids = [m.resource_id for m in db.query(Membership).filter_by(
        user_id=user.id, resource_type="project"
    ).all()]
    return db.query(Project).filter(Project.id.in_(project_ids)).all()
```

### Protecting routes by membership

Use `require_membership` to ensure the user belongs to the resource:
```python
from auth_middleware import require_membership

@router.get("/projects/{project_id}/tasks")
def get_tasks(project_id: int,
              member = Depends(require_membership("project")),
              db = Depends(get_db)):
    # Only runs if user is a member of this project
    return db.query(Task).filter_by(project_id=project_id).all()
```

### Invite links

Users can generate invite codes to share:
```
POST /api/auth/invites   → creates invite code for a resource
POST /api/auth/invites/{code}/accept   → joins the resource
```

## Frontend Components for Membership

### MemberList — show who's in a resource

```tsx
import { MemberList } from './components/auth/MemberList'

// In your project settings or sidebar:
<MemberList
  resourceType="project"
  resourceId={project.id}
  currentUserRole={myRole}  // "owner", "admin", "member" — controls remove buttons
/>
```

### InviteModal — create & accept invite codes

```tsx
import { InviteModal } from './components/auth/InviteModal'

<InviteModal
  resourceType="project"
  resourceId={project.id}
  isOpen={showInvite}
  onClose={() => setShowInvite(false)}
/>
```

The modal has two sections:
- **Create invite** — generates a code the owner can share
- **Join with code** — paste an invite code to join

### ProfilePage — edit account & change password

```tsx
import { ProfilePage } from './components/auth/ProfilePage'

// As a page or modal content:
{showProfile && <ProfilePage onClose={() => setShowProfile(false)} />}
```

### UserMenu — already includes link to profile

The `UserMenu` component shows the user dropdown with sign-out. The agent should add
a "Profile" option that opens `ProfilePage`.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/auth/register | No | Create account (first user = admin) |
| POST | /api/auth/login | No | Login, returns JWT |
| GET | /api/auth/me | Yes | Get current user |
| PUT | /api/auth/me | Yes | Update profile (username, email) |
| PUT | /api/auth/me/password | Yes | Change password |
| POST | /api/auth/logout | No | Client-side logout |
| GET | /api/auth/users | Admin | List all users |
| GET | /api/auth/members/{type}/{id} | Member | List members of a resource |
| POST | /api/auth/members/{type}/{id} | Owner | Add a member to a resource |
| DELETE | /api/auth/members/{type}/{id}/{uid} | Owner | Remove a member |
| POST | /api/auth/invites | Owner | Create an invite link |
| POST | /api/auth/invites/{code}/accept | Yes | Accept invite and join |
