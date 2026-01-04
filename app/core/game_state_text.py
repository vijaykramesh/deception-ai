from __future__ import annotations

from dataclasses import dataclass

from app.api.models import GameState
from app.assets.registry import GameAssets


@dataclass(frozen=True, slots=True)
class GameStateParagraphOptions:
    viewer_player_id: str | None = None


def _player_label(display_name: str | None, player_id: str) -> str:
    return display_name or player_id


def _sorted_players(state: GameState):
    return sorted(state.players, key=lambda p: p.seat)


def _normalize_pov(pov: str) -> str:
    """Normalize POV values to the supported set.

    Anything unknown is treated as investigator for safety (most restrictive).
    """

    allowed = {"fs", "murderer", "accomplice", "witness", "investigator"}
    return pov if pov in allowed else "investigator"


def _can_see_solution(*, pov: str) -> bool:
    pov = _normalize_pov(pov)
    return pov in {"fs", "murderer", "accomplice"}


def _can_see_identities(*, pov: str) -> bool:
    """Whether the POV should see role identities.

    Rules:
    - FS sees all roles.
    - Witness sees murderer + accomplice identities (not the solution).
    - Murderer and accomplice know each other.
    - Investigators do not see any hidden identities.
    """

    pov = _normalize_pov(pov)
    return pov in {"fs", "witness", "murderer", "accomplice"}


def _format_player_cards(*, state: GameState, assets: GameAssets, pov: str) -> str:
    """LLM-friendly public-table section.

    Intended rule for prompts:
    - Everyone can see every player's cards (including their own).
      (Players still don't know which ones are selected for the solution.)

    We group deterministically by seat order, but we don't use seat numbers as the primary identifier.
    """

    pov = _normalize_pov(pov)
    players = _sorted_players(state)

    if not players:
        return ""

    header = "PUBLIC TABLE (all hands visible; ordered by seating):" if pov != "fs" else "HANDS (FS can see all):"

    lines: list[str] = [header]
    for p in players:
        means = [
            assets.means_cards.get(mid).name if assets.means_cards.get(mid) else mid
            for mid in p.hand.means_ids
        ]
        clues = [
            assets.clue_cards.get(cid).name if assets.clue_cards.get(cid) else cid
            for cid in p.hand.clue_ids
        ]
        label = _player_label(p.display_name, p.player_id)
        lines.append(f"- {label}")
        lines.append(f"  - Means: {means}")
        lines.append(f"  - Clues: {clues}")

    return "\n".join(lines).strip()


def game_state_to_paragraph(
    *,
    state: GameState,
    assets: GameAssets,
    pov: str,
    viewer_player_id: str | None = None,
) -> str:
    """Deterministic single-paragraph summary with POV-based redaction.

    POV values match UI toggles: fs, murderer, accomplice, witness, investigator.

    Note: we accept `viewer_player_id` for compatibility, but prompts use the rule
    that all hands are visible to all players (including their own).
    """

    pov = _normalize_pov(pov)
    players = _sorted_players(state)

    fs = next((p for p in players if p.role == "forensic_scientist"), None)
    murderer = next((p for p in players if p.role == "murderer"), None)
    accomplice = next((p for p in players if p.role == "accomplice"), None)
    witness = next((p for p in players if p.role == "witness"), None)

    sent: list[str] = []

    # Scene tiles (public). Resolve to human text when possible.
    if state.fs_location_id and state.fs_cause_id:
        loc_opt = assets.location_and_cause_of_death_tiles.get(state.fs_location_id)
        cause_opt = assets.location_and_cause_of_death_tiles.get(state.fs_cause_id)
        loc_txt = loc_opt.option if loc_opt is not None else state.fs_location_id
        cause_txt = cause_opt.option if cause_opt is not None else state.fs_cause_id
        sent.append(f"Scene: Location is '{loc_txt}' and Cause of Death is '{cause_txt}'.")
    else:
        sent.append("Scene: Location and Cause of Death have not been selected yet.")

    # Roles / identities.
    if fs is not None:
        sent.append(f"Forensic Scientist: {_player_label(fs.display_name, fs.player_id)}.")

    if _can_see_identities(pov=pov):
        if pov == "fs":
            if murderer is not None:
                sent.append(f"Murderer: {_player_label(murderer.display_name, murderer.player_id)}.")
            if accomplice is not None:
                sent.append(f"Accomplice: {_player_label(accomplice.display_name, accomplice.player_id)}.")
            if witness is not None:
                sent.append(f"Witness: {_player_label(witness.display_name, witness.player_id)}.")
        elif pov == "witness":
            if murderer is not None:
                sent.append(f"Murderer: {_player_label(murderer.display_name, murderer.player_id)}.")
            if accomplice is not None:
                sent.append(f"Accomplice: {_player_label(accomplice.display_name, accomplice.player_id)}.")
        elif pov in {"murderer", "accomplice"}:
            # Murderer/accomplice know each other.
            if murderer is not None:
                sent.append(f"Murderer: {_player_label(murderer.display_name, murderer.player_id)}.")
            if accomplice is not None:
                sent.append(f"Accomplice: {_player_label(accomplice.display_name, accomplice.player_id)}.")

    # Murder solution.
    if _can_see_solution(pov=pov) and state.solution is not None and murderer is not None:
        means_card = assets.means_cards.get(state.solution.means_id)
        clue_card = assets.clue_cards.get(state.solution.clue_id)
        means_txt = means_card.name if means_card is not None else state.solution.means_id
        clue_txt = clue_card.name if clue_card is not None else state.solution.clue_id
        sent.append(f"Murder solution (secret): the murderer chose Means '{means_txt}' and Evidence '{clue_txt}'.")

    public_table = _format_player_cards(state=state, assets=assets, pov=pov)
    if public_table:
        sent.append(public_table)

    return " ".join(sent)
