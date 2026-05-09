"""IR + plan + report dataclasses for the task-generator agent."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Union


@dataclass
class TaskNode:
    title: str
    description_md: str
    type_marker: str | None = None
    related_refs: list[str] = field(default_factory=list)


@dataclass
class StoryNode:
    title: str
    description_md: str
    type_marker: str | None = None
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


ParseWarningKind = Literal[
    "orphan_story",
    "multiple_h2",
    "unknown_section",
    "no_h2",
    "fenced_code_heading",
]


@dataclass
class ParseWarning:
    kind: ParseWarningKind
    detail: str


@dataclass
class CreateWorkItem:
    node_kind: Literal["epic", "story", "task"]
    title: str
    description_html: str
    type_id_key: Literal["epic", "story", "task"]
    parent_ref: str | None
    ref_key: str
    label_keys: list[str] = field(default_factory=list)


@dataclass
class AddComment:
    target_ref_key: str
    comment_html: str


@dataclass
class UpdateWorkItem:
    target_ref_key: str
    patch: dict


@dataclass
class CreateLabel:
    name: str
    color: str = "#888"


Op = Union[CreateWorkItem, AddComment, UpdateWorkItem, CreateLabel]


@dataclass
class RunPlan:
    plane_ops: list[Op]
    grava_ops: list[Op]
    preview_path: Path
    warnings: list[ParseWarning]


@dataclass
class RunReport:
    plane_created: list[dict] = field(default_factory=list)
    plane_updated: list[dict] = field(default_factory=list)
    plane_comments: list[dict] = field(default_factory=list)
    plane_orphans: list[dict] = field(default_factory=list)
    grava_created: list[dict] = field(default_factory=list)
    grava_updated: list[dict] = field(default_factory=list)
    grava_anomalies: list[dict] = field(default_factory=list)
    grava_orphans: list[dict] = field(default_factory=list)
    grava_commit_hash: str | None = None
    started_at: str = ""
    finished_at: str = ""
    spec_page_id: str = ""
    run_id: str = ""
    failed_op: dict | None = None
    rolled_back: bool = False


@dataclass
class RunState:
    run_id: str
    project_id: str
    page_id: str
    started_at: str
    ops_total: int
    completed_op_indices: list[int] = field(default_factory=list)
    ref_to_uuid: dict[str, str] = field(default_factory=dict)
    ref_to_sequence_id: dict[str, int] = field(default_factory=dict)
    failed_op_index: int | None = None
    failure_detail: str | None = None
    rolled_back: bool = False


@dataclass
class GravaState:
    run_id: str
    target_repo: str
    started_at: str
    ops_total: int
    completed_op_indices: list[int] = field(default_factory=list)
    ref_to_grava_id: dict[str, str] = field(default_factory=dict)
    plane_comments_posted: list[str] = field(default_factory=list)
    failed_op_index: int | None = None
    failure_detail: str | None = None
    rolled_back: bool = False
    grava_commit_hash: str | None = None
