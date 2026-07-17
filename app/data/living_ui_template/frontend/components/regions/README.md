# App regions (AUTO-MOUNTED)

Every `NN_slug.tsx` file in this folder is auto-discovered and rendered by
MainView, in filename order — you never edit MainView to mount a region.

- **One region per screen area** (a feature/panel/section of the app).
- **`export default`** a React component (no props): `export default function Practice() { ... }`.
- **Order = filename**: `01_...`, `02_...`, ... render top to bottom.
- The wireframe stubs render shadcn `<Skeleton>` placeholders; each feature
  build **replaces its region file in place** with the real component.
- To add a region: create the file. To change one: edit it. To remove one:
  delete it. Mounting is automatic in all three cases.

Region components own their own data (via `../../api.gen` / `useEntities`)
and layout (Tailwind + shadcn). A region file that still renders only
`<Skeleton>` is an unbuilt placeholder and fails validation.
