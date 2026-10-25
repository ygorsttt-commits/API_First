"""Contracts for every structured AI output. Anything the model returns is validated against these
models before it is persisted or acted upon; cross-field validators reject inconsistent plans."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {what} id '{i}'")
        seen.add(i)


# ---------------------------------------------------------------- requirements


class Requirement(_Strict):
    id: str = Field(description="Stable identifier such as FR-1 or NFR-2")
    title: str
    description: str
    priority: Literal["must", "should", "could"]


class AcceptanceCriterion(_Strict):
    id: str = Field(description="Identifier such as AC-1")
    requirement_id: str
    given: str
    when: str
    then: str


class RequirementsSpec(_Strict):
    project_name: str
    summary: str
    functional_requirements: list[Requirement]
    non_functional_requirements: list[Requirement]
    assumptions: list[str]
    acceptance_criteria: list[AcceptanceCriterion]
    open_questions: list[str]
    out_of_scope: list[str]

    @model_validator(mode="after")
    def _consistency(self) -> RequirementsSpec:
        if not self.functional_requirements:
            raise ValueError("at least one functional requirement is required")
        req_ids = [r.id for r in self.functional_requirements + self.non_functional_requirements]
        _unique(req_ids, "requirement")
        _unique([c.id for c in self.acceptance_criteria], "acceptance criterion")
        known = set(req_ids)
        for c in self.acceptance_criteria:
            if c.requirement_id not in known:
                raise ValueError(
                    f"acceptance criterion {c.id} references unknown requirement {c.requirement_id}"
                )
        return self


# ---------------------------------------------------------------- architecture


class Component(_Strict):
    name: str
    responsibility: str
    technology: str


class EntityField(_Strict):
    name: str
    type: Literal["string", "text", "integer", "number", "boolean", "datetime"]
    required: bool


class Entity(_Strict):
    name: str
    fields: list[EntityField]


class Endpoint(_Strict):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    description: str


class Decision(_Strict):
    title: str
    decision: str
    rationale: str
    alternatives: list[str]


class Risk(_Strict):
    description: str
    severity: Literal["low", "medium", "high"]
    mitigation: str


class ArchitectureSpec(_Strict):
    overview: str
    style: str
    components: list[Component]
    data_model: list[Entity]
    api_endpoints: list[Endpoint]
    decisions: list[Decision]
    risks: list[Risk]
    deployment: str

    @model_validator(mode="after")
    def _consistency(self) -> ArchitectureSpec:
        if not self.components:
            raise ValueError("architecture needs at least one component")
        _unique([e.name for e in self.data_model], "entity")
        for ep in self.api_endpoints:
            if not ep.path.startswith("/"):
                raise ValueError(f"endpoint path must start with '/': {ep.path}")
        return self


# ---------------------------------------------------------------- task plan


class PlanTask(_Strict):
    id: str = Field(description="Identifier such as T-1")
    title: str
    description: str
    capability: Literal["development", "testing", "security", "infrastructure", "release"]
    depends_on: list[str]
    acceptance_criteria_ids: list[str]


class TaskPlan(_Strict):
    milestones: list[str]
    tasks: list[PlanTask]

    @model_validator(mode="after")
    def _dag(self) -> TaskPlan:
        if not self.tasks:
            raise ValueError("plan needs at least one task")
        ids = [t.id for t in self.tasks]
        _unique(ids, "task")
        known = set(ids)
        graph = {t.id: t.depends_on for t in self.tasks}
        for t in self.tasks:
            for d in t.depends_on:
                if d not in known:
                    raise ValueError(f"task {t.id} depends on unknown task {d}")
        # cycle detection (iterative DFS)
        state: dict[str, int] = {}
        for start in ids:
            if state.get(start):
                continue
            stack: list[tuple[str, int]] = [(start, 0)]
            while stack:
                node, idx = stack.pop()
                if idx == 0:
                    state[node] = 1
                deps = graph[node]
                if idx < len(deps):
                    stack.append((node, idx + 1))
                    nxt = deps[idx]
                    if state.get(nxt) == 1:
                        raise ValueError(f"dependency cycle involving task {nxt}")
                    if not state.get(nxt):
                        stack.append((nxt, 0))
                else:
                    state[node] = 2
        return self


# ---------------------------------------------------------------- code generation


class GeneratedFile(_Strict):
    path: str = Field(description="Relative POSIX path inside the project workspace")
    content: str
    purpose: str


class CodeBundle(_Strict):
    files: list[GeneratedFile]
    notes: list[str]

    @model_validator(mode="after")
    def _paths(self) -> CodeBundle:
        if not self.files:
            raise ValueError("bundle must contain at least one file")
        _unique([f.path for f in self.files], "file path")
        return self


# ---------------------------------------------------------------- security review


class SecurityReview(_Strict):
    summary: str
    risks: list[Risk]
    recommendation: Literal["proceed", "proceed_with_caution", "block"]
