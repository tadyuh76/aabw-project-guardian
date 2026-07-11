"""Versioned, controlled owner and action recommendations."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, field_validator

from guardian_voc.schemas.analysis import FrozenModel, PrimaryTopic
from guardian_voc.schemas.insights import Team


PLAYBOOK_VERSION = "guardian-action-playbooks-v1"
_PLAYBOOK_PATH = Path(__file__).resolve().parents[1] / "taxonomy" / "action_playbooks.yaml"


class ActionPlaybook(FrozenModel):
    topic: PrimaryTopic
    primary_owner: Team
    supporting_owner: Team | None
    actions: tuple[str, ...]
    viewer_actions: dict[str, str] = Field(default_factory=dict)

    @field_validator("actions")
    @classmethod
    def action_limit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > 2:
            raise ValueError("playbook must contain one or two actions")
        return value


@lru_cache(maxsize=1)
def load_playbooks() -> dict[PrimaryTopic, ActionPlaybook]:
    with _PLAYBOOK_PATH.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if raw.get("version") != PLAYBOOK_VERSION:
        raise RuntimeError("unsupported playbook version")
    playbooks = {
        PrimaryTopic(topic): ActionPlaybook(
            topic=PrimaryTopic(topic),
            primary_owner=spec["primary_owner"],
            supporting_owner=spec.get("supporting_owner"),
            actions=tuple(spec["actions"]),
            viewer_actions=dict(spec.get("viewer_actions", {})),
        )
        for topic, spec in raw["topics"].items()
    }
    missing = set(PrimaryTopic) - set(playbooks)
    if missing:
        raise RuntimeError(f"playbooks missing topics: {sorted(item.value for item in missing)}")
    return playbooks


def get_playbook(topic: PrimaryTopic) -> ActionPlaybook:
    return load_playbooks()[topic]


def viewer_action(topic: PrimaryTopic, role: str) -> str | None:
    if role == "leadership":
        return None
    return get_playbook(topic).viewer_actions.get(role)
