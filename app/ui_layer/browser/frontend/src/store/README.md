# store/

Redux Toolkit store for the CraftBot frontend. Replaces ad-hoc contexts with a single, layered, well-typed state container.

## Layout

```
store/
├── index.ts          configureStore, RootState, AppDispatch
├── hooks.ts          useAppSelector, useAppDispatch (typed)
├── socket/           transport layer (middleware-owned; not for component consumption)
├── slices/           one file per domain (connection, messages, tasks, agent, ...)
├── selectors/        memoized read API; one file per slice
└── thunks/           async/multi-step orchestration when reducers aren't enough
```

## Rules

1. **Components** import only from `store/hooks`, `store/selectors/*`, and slice action creators (default-imported from `slices/<name>Slice.ts`). They never touch `store/socket/*`.
2. **Slices** are pure: they never import from `store/socket/*`. To send something over the wire, attach `meta.socket` to an action. The socket middleware handles the I/O.
3. **One slice = one domain.** Resist sharing files. If two slices need to coordinate, use a thunk.
4. **Every slice gets selectors.** Create `selectors/<name>.ts` the same day you create the slice — even if it's three one-liners. Components depend on the selector layer for memoization stability and so we can refactor slice shape later.
5. **Normalize collections.** Use `createEntityAdapter` for any list of entities with IDs (messages, tasks, projects, files). Don't store as plain arrays.
6. **Cache aggressively, invalidate on push.** Static-during-session data (skill meta, model providers, living-ui list) is fetched once and reused. Server push events trigger invalidations.

## Adding a new slice

1. Create `slices/<name>Slice.ts` — define state, initial state, reducers, export action creators + reducer.
2. Register the reducer in `store/index.ts`.
3. Create `selectors/<name>.ts` with at least the top-level selectors.
4. If the slice talks to the socket, register inbound message handlers in `socket/messageRegistry.ts`.
5. Replace the legacy context consumers one at a time. Keep the legacy code working until all consumers have migrated.
