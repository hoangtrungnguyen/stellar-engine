# systems/

This folder contains specification and planning documents for every system managed by stellar-engine.

## System types

There are two kinds of systems:

- **Main system** — the company's primary codebase. The root `repo-map.yaml` and root Plane configuration point here. stellar-engine's agents (task-generator, orchestrator, generator) default to this system.
- **Support system** — an external or auxiliary system the company integrates with. Has its own `system.yaml` (own Plane project UUID + repo) and is registered separately. Support systems do not override root Plane config.

## Structure

```
systems/
  <SystemName>/          # one folder per system (main or support)
    system.yaml          # task-generator config: Plane UUID → git repo + state map
    CLAUDE.md            # system-level context: type, Plane project, tech stack, doc map
    <project>/           # one sub-folder per project within the system
      CLAUDE.md          # project-level context
      *.md               # specs, stories, flows
```

Each `<SystemName>` folder is an independent product or platform. Each `<project>` folder inside it is a vertical slice (e.g. a sub-app, a service, a domain area).

## Systems index

| System | Type | Folder | Plane identifier | Notes |
|---|---|---|---|---|
| SportBuddies | main | `SportBuddies/` | `SPACE` | **TEST** — example/reference folder only; not a real production system |

## Conventions

- Every system folder has a `CLAUDE.md` with: system type (main/support), Plane project UUID, tech stack, document map, and architectural rules.
- Every project folder has its own `CLAUDE.md` scoped to that project's stories, flows, and constraints.
- Do not add application source code here — this tree is specs only.
- When adding a new system, create `systems/<SystemName>/CLAUDE.md`, add a `system.yaml`, and add a row to the table above.
- Only one system should be designated **main** at a time — it is the one the root `repo-map.yaml` and Plane config refer to.
- All `se` commands default to the main system. Support systems must be targeted explicitly via their own `system.yaml` (pass the relevant project UUID or `--system` flag when applicable).
