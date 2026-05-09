# systems/

This folder contains specification and planning documents for every system managed by stellar-engine.

## Structure

```
systems/
  <SystemName>/          # one folder per system
    CLAUDE.md            # system-level context: Plane project, tech stack, doc map
    <project>/           # one sub-folder per project within the system
      CLAUDE.md          # project-level context
      *.md               # specs, stories, flows
```

Each `<SystemName>` folder is an independent product or platform. Each `<project>` folder inside it is a vertical slice (e.g. a sub-app, a service, a domain area).

## Systems index

| System | Folder | Plane identifier | Notes |
|---|---|---|---|
| SportBuddies | `SportBuddies/` | `SPACE` | Sports court booking marketplace, Ho Chi Minh City (Sai Gon) |

## Conventions

- Every system folder has a `CLAUDE.md` with: Plane project UUID, tech stack, document map, and architectural rules.
- Every project folder has its own `CLAUDE.md` scoped to that project's stories, flows, and constraints.
- Do not add application source code here — this tree is specs only.
- When adding a new system, create `systems/<SystemName>/CLAUDE.md` and add a row to the table above.
