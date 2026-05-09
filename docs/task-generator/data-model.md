# Data Model

Internal representations passed between parser, planner, writers, and reconciler. Lives in `agents/task-generator/ir.py` (plus a small `repo_map.py` for the project-to-repo lookup).

## IR (parser output)

```python
# ir.py
from dataclasses import dataclass, field

@dataclass
class TaskNode:
    title: str
    description_md: str
    type_marker: str | None       # "Bug", "P0", etc. — overrides default task type
    related_refs: list[str] = field(default_factory=list)

@dataclass
class StoryNode:
    title: str
    description_md: str
    type_marker: str | None
    tasks: list[TaskNode] = field(default_factory=list)
    related_refs: list[str] = field(default_factory=list)

@dataclass
class EpicNode:
    title: str
    description_md: str
    spec_page_url: str
    spec_page_id: str
    open_questions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    stories: list[StoryNode] = field(default_factory=list)
    related_refs: list[str] = field(default_factory=list)
```

## RunPlan (planner output)

```python
@dataclass
class RunPlan:
    plane_ops: list[Op]           # ordered; executed sequentially
    grava_ops: list[Op]           # ordered; executed after Plane completes
    preview_path: Path
    warnings: list[ParseWarning]
```

`Op` is a small tagged union of `CreateWorkItem`, `UpdateWorkItem`, `DeleteWorkItem`, `AddComment`, `CreateLabel`, etc. Each carries enough context for the writer to execute and for the preview to render.

## RunReport (writer output)

```python
@dataclass
class RunReport:
    plane_created: list[dict]     # [{type, sequence_id, uuid, title}]
    plane_updated: list[dict]     # field-by-field diffs applied
    plane_orphans: list[dict]     # items in Plane but not in spec
    grava_created: list[dict]
    grava_orphans: list[dict]
    started_at: str
    finished_at: str
    spec_page_id: str
```

Serialised to `runs/<timestamp>.json`.

## repo-map.yaml

```yaml
# stellar-engine/repo-map.yaml
projects:
  "<plane-project-uuid-1>":
    repo: /Users/trungnguyenhoang/IdeaProjects/sportbuddies
    workspace_prefix: SPORT
  "<plane-project-uuid-2>":
    repo: /Users/trungnguyenhoang/IdeaProjects/stellar-engine
    workspace_prefix: STELLAR
```

`repo_map.py` returns the matching entry by Plane project UUID; the agent fails fast if the project isn't mapped (orchestrator's responsibility to keep the file current).

## See Also

- [parser.md](parser.md) — produces the IR.
- [planner.md](planner.md) — consumes the IR, produces the `RunPlan`.
- [writers.md](writers.md) — consume the `RunPlan`, produce the `RunReport`.
