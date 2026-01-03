from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import redis

from app.api.models import GamePhase, GameState
from app.fsm import GameFSM
from app.game_store import get_game, save_game
from app.lock import game_lock
from app.streams import Mailbox, publish_many


ActionName = Literal["murder", "fs_scene", "discuss", "solve"]


@dataclass(frozen=True, slots=True)
class ActionResult:
    state: GameState
    mailbox_entry_ids: list[str]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _mailbox_entries_for_state_changed(*, state: GameState) -> list[tuple[str, dict[str, str]]]:
    gid = str(state.game_id)
    payload = {
        "type": "state_changed",
        "game_id": gid,
        "phase": state.phase.value,
        "ts": _now_iso(),
    }
    return [(Mailbox(game_id=gid, player_id=p.player_id).key, payload) for p in state.players]


def _mailbox_entries_for_murder_prompt(*, state: GameState) -> list[tuple[str, dict[str, str]]]:
    gid = str(state.game_id)
    murderer = next((p for p in state.players if p.role == "murderer"), None)
    if murderer is None:
        return []
    return [
        (
            Mailbox(game_id=gid, player_id=murderer.player_id).key,
            {
                "type": "prompt_murder_pick",
                "game_id": gid,
                "player_id": murderer.player_id,
                "phase": state.phase.value,
                "clue_ids": ",".join(murderer.hand.clue_ids),
                "means_ids": ",".join(murderer.hand.means_ids),
                "ts": _now_iso(),
            },
        )
    ]


def _mailbox_entries_for_murder_picked(*, state: GameState) -> list[tuple[str, dict[str, str]]]:
    gid = str(state.game_id)
    entries: list[tuple[str, dict[str, str]]] = []

    murderer = next((p for p in state.players if p.role == "murderer"), None)
    accomplice = next((p for p in state.players if p.role == "accomplice"), None)
    witness = next((p for p in state.players if p.role == "witness"), None)
    fs = next((p for p in state.players if p.role == "forensic_scientist"), None)

    # Solution chosen notification (to those who know solution).
    if state.solution is not None:
        for p in [murderer, accomplice, fs]:
            if p is None:
                continue
            entries.append(
                (
                    Mailbox(game_id=gid, player_id=p.player_id).key,
                    {
                        "type": "murder_solution_chosen",
                        "game_id": gid,
                        "player_id": p.player_id,
                        "clue_id": state.solution.clue_id,
                        "means_id": state.solution.means_id,
                        "ts": _now_iso(),
                    },
                )
            )

    # Witness identity reveal.
    if witness is not None:
        entries.append(
            (
                Mailbox(game_id=gid, player_id=witness.player_id).key,
                {
                    "type": "witness_identities_revealed",
                    "game_id": gid,
                    "player_id": witness.player_id,
                    "murderer_id": witness.known_murderer_id or "",
                    "accomplice_id": witness.known_accomplice_id or "",
                    "ts": _now_iso(),
                },
            )
        )

    return entries


def _mailbox_entries_for_fs_scene_prompt(*, state: GameState) -> list[tuple[str, dict[str, str]]]:
    """Prompt the Forensic Scientist to pick the public Location + Cause of Death tiles."""

    gid = str(state.game_id)
    fs = next((p for p in state.players if p.role == "forensic_scientist"), None)
    if fs is None:
        return []

    from app.game_store import _cause_ids_from_assets, _location_ids_from_assets

    location_ids = _location_ids_from_assets()
    cause_ids = _cause_ids_from_assets()

    return [
        (
            Mailbox(game_id=gid, player_id=fs.player_id).key,
            {
                "type": "prompt_fs_scene_pick",
                "game_id": gid,
                "player_id": fs.player_id,
                "phase": state.phase.value,
                "location_ids": ",".join(location_ids),
                "cause_ids": ",".join(cause_ids),
                "ts": _now_iso(),
            },
        )
    ]


def _mailbox_entries_for_fs_scene_picked(*, state: GameState) -> list[tuple[str, dict[str, str]]]:
    gid = str(state.game_id)
    if not state.fs_location_id or not state.fs_cause_id:
        return []

    payload = {
        "type": "fs_scene_selected",
        "game_id": gid,
        "location_id": state.fs_location_id,
        "cause_id": state.fs_cause_id,
        "ts": _now_iso(),
    }
    return [(Mailbox(game_id=gid, player_id=p.player_id).key, payload) for p in state.players]


def dispatch_action(*, r: redis.Redis, game_id: UUID, player_id: str, action: ActionName, payload: dict[str, Any]) -> ActionResult:
    """Entry point for human UI + agent runner.

    Applies an action by:
    - loading game state
    - acquiring a per-game lock
    - validating transition via FSM
    - mutating state via existing game_store helpers
    - persisting state
    - emitting mailbox messages (Redis Streams)

    Notes:
    - This is scaffolding; we currently emit a simple `state_changed` message to every
      player's mailbox. Later you can emit per-player prompts / hidden info / etc.
    """

    gid_str = str(game_id)

    with game_lock(r=r, game_id=gid_str):
        state = get_game(r=r, game_id=game_id)
        if state is None:
            raise ValueError("Game not found")

        fsm = GameFSM(state)

        # Domain handlers + FSM transitions.
        if action == "murder":
            if fsm.current_state != fsm.awaiting_murder_pick:
                raise ValueError("Game is not awaiting murder selection")

            clue = str(payload.get("clue"))
            means = str(payload.get("means"))

            # Use the existing domain logic.
            from app.game_store import set_murder_solution

            # set_murder_solution is async; in dispatched sync path we keep things sync.
            # The FastAPI route can call the async version directly; the dispatcher is
            # used for tests and future generic endpoint.
            raise RuntimeError("Use async dispatcher for murder action")

        elif action == "discuss":
            if state.phase == GamePhase.completed:
                raise ValueError("Game is completed")
            comments = str(payload.get("comments"))
            from app.game_store import add_discussion_comment

            state = add_discussion_comment(r=r, game_id=game_id, player_id=player_id, comments=comments)
            fsm = GameFSM(state)

        elif action == "solve":
            if fsm.current_state != fsm.discussion:
                raise ValueError("Game is not in discussion phase")
            from app.game_store import submit_solution_guess

            state = submit_solution_guess(
                r=r,
                game_id=game_id,
                player_id=player_id,
                murderer_id=str(payload.get("murderer")),
                clue_id=str(payload.get("clue")),
                means_id=str(payload.get("means")),
            )
            # Sync phase based on state.phase already set by domain function.
            fsm = GameFSM(state)

        else:
            raise ValueError(f"Unknown action: {action}")

        fsm.sync_phase_to_model()
        save_game(r=r, state=state)

        mailbox_entries = _mailbox_entries_for_state_changed(state=state)
        ids = publish_many(r=r, entries=mailbox_entries)

        return ActionResult(state=state, mailbox_entry_ids=ids)


async def dispatch_action_async(
    *,
    r: redis.Redis,
    game_id: UUID,
    player_id: str,
    action: ActionName,
    payload: dict[str, Any],
) -> ActionResult:
    gid_str = str(game_id)

    with game_lock(r=r, game_id=gid_str):
        state = get_game(r=r, game_id=game_id)
        if state is None:
            raise ValueError("Game not found")

        fsm = GameFSM(state)

        did_murder_pick = False
        did_fs_scene_pick = False

        if action == "murder":
            if fsm.current_state != fsm.awaiting_murder_pick:
                raise ValueError("Game is not awaiting murder selection")
            from app.game_store import set_murder_solution

            state = await set_murder_solution(
                r=r,
                game_id=game_id,
                player_id=player_id,
                clue_id=str(payload.get("clue")),
                means_id=str(payload.get("means")),
            )
            did_murder_pick = True
            fsm = GameFSM(state)

        elif action == "fs_scene":
            if state.phase != GamePhase.setup_awaiting_fs_scene_pick:
                raise ValueError("Game is not awaiting forensic scientist scene selection")
            from app.game_store import set_fs_scene_selection

            state = await set_fs_scene_selection(
                r=r,
                game_id=game_id,
                player_id=player_id,
                location_id=str(payload.get("location")),
                cause_id=str(payload.get("cause")),
            )
            did_fs_scene_pick = True
            fsm = GameFSM(state)

        elif action == "discuss":
            if state.phase == GamePhase.completed:
                raise ValueError("Game is completed")
            from app.game_store import add_discussion_comment

            state = add_discussion_comment(
                r=r,
                game_id=game_id,
                player_id=player_id,
                comments=str(payload.get("comments")),
            )
            fsm = GameFSM(state)

        elif action == "solve":
            if fsm.current_state != fsm.discussion:
                raise ValueError("Game is not in discussion phase")
            from app.game_store import submit_solution_guess

            state = submit_solution_guess(
                r=r,
                game_id=game_id,
                player_id=player_id,
                murderer_id=str(payload.get("murderer")),
                clue_id=str(payload.get("clue")),
                means_id=str(payload.get("means")),
            )
            fsm = GameFSM(state)

        else:
            raise ValueError(f"Unknown action: {action}")

        fsm.sync_phase_to_model()
        save_game(r=r, state=state)

        entries: list[tuple[str, dict[str, str]]] = []
        # Always notify everyone that state changed.
        entries.extend(_mailbox_entries_for_state_changed(state=state))
        # If we just completed the murder pick step, also send role-specific info and FS prompt.
        if did_murder_pick:
            entries.extend(_mailbox_entries_for_murder_picked(state=state))
            entries.extend(_mailbox_entries_for_fs_scene_prompt(state=state))
        if did_fs_scene_pick:
            entries.extend(_mailbox_entries_for_fs_scene_picked(state=state))

        ids = publish_many(r=r, entries=entries)
        return ActionResult(state=state, mailbox_entry_ids=ids)
