from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.context import RoleContext
from app.prompts import load_prompt


class RoleName(str, Enum):
    forensic_scientist = "forensic_scientist"
    murderer = "murderer"
    accomplice = "accomplice"
    witness = "witness"
    investigator = "investigator"


@dataclass(frozen=True, slots=True)
class RoleSpec:
    name: RoleName
    prompt_file: str


ROLE_SPECS: dict[RoleName, RoleSpec] = {
    RoleName.forensic_scientist: RoleSpec(RoleName.forensic_scientist, "forensic_scientist.txt"),
    RoleName.murderer: RoleSpec(RoleName.murderer, "murderer.txt"),
    RoleName.accomplice: RoleSpec(RoleName.accomplice, "accomplice.txt"),
    RoleName.witness: RoleSpec(RoleName.witness, "witness.txt"),
    RoleName.investigator: RoleSpec(RoleName.investigator, "investigator.txt"),
}


def load_role_prompt(role: RoleName | str) -> str:
    role_name = RoleName(role) if not isinstance(role, RoleName) else role
    spec = ROLE_SPECS[role_name]
    return load_prompt(spec.prompt_file)


def make_role_context(role: RoleName | str) -> RoleContext:
    role_name = RoleName(role) if not isinstance(role, RoleName) else role
    return RoleContext(role_name=role_name.value, prompt=load_role_prompt(role_name))

