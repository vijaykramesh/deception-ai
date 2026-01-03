from __future__ import annotations

import random
from datetime import UTC, datetime

from app.agents.factory import create_default_agent
from app.agents.solution_picker import SolutionPickError, pick_solution_with_agent
from app.api.models import GameState, PlayerHand, PlayerState, Solution
from app.assets.registry import GameAssets
from app.contexts import make_base_player_context
from app.core.context import PlayerContext, compose_context
from app.roles import RoleName, make_role_context


def _now() -> datetime:
    return datetime.now(tz=UTC)


def assign_roles(*, total_players: int, rng: random.Random) -> list[str]:
    """Return a list of role names, length == total_players.

    Rules:
    - Always: 1 forensic_scientist, 1 murderer, 2 investigators.
    - If 6–12 players: also 1 accomplice and 1 witness.
    - Remaining seats are investigators.
    """

    if total_players < 4 or total_players > 12:
        raise ValueError("total_players must be between 4 and 12")

    roles: list[str] = [
        RoleName.forensic_scientist.value,
        RoleName.murderer.value,
        RoleName.investigator.value,
        RoleName.investigator.value,
    ]

    if total_players >= 6:
        roles.extend([RoleName.accomplice.value, RoleName.witness.value])

    while len(roles) < total_players:
        roles.append(RoleName.investigator.value)

    rng.shuffle(roles)
    return roles


def build_initial_players(
    *,
    num_ai_players: int,
    num_human_players: int,
    rng: random.Random,
) -> list[PlayerState]:
    total = num_ai_players + num_human_players
    roles = assign_roles(total_players=total, rng=rng)

    players: list[PlayerState] = []
    # Seats are 0..total-1. First num_human as humans, rest AI.
    for seat in range(total):
        is_ai = seat >= num_human_players
        pid = f"p{seat+1}"
        players.append(PlayerState(player_id=pid, seat=seat, is_ai=is_ai, role=roles[seat]))

    return players


def _find_player(players: list[PlayerState], role: str) -> PlayerState | None:
    return next((p for p in players if p.role == role), None)


def apply_solution_and_secrets(*, state: GameState, solution: Solution) -> None:
    """Apply the chosen solution to the game state.

    - Stores the canonical solution at game level.
    - Copies the solution into FS/murderer/accomplice prompts.
    - Sets witness-only identity knowledge (murderer/accomplice ids) but DOES NOT give the witness the solution.
    """

    state.solution = solution

    murderer = _find_player(state.players, RoleName.murderer.value)
    accomplice = _find_player(state.players, RoleName.accomplice.value)

    # Copy solution to specific roles.
    for p in state.players:
        if p.role in {
            RoleName.forensic_scientist.value,
            RoleName.murderer.value,
            RoleName.accomplice.value,
        }:
            p.knows_solution = True
            p.solution = solution
        else:
            p.knows_solution = False
            p.solution = None

    # Witness gets identities only.
    for p in state.players:
        if p.role == RoleName.witness.value:
            p.knows_identities = True
            p.known_murderer_id = murderer.player_id if murderer else None
            p.known_accomplice_id = accomplice.player_id if accomplice else None
        else:
            p.knows_identities = False
            p.known_murderer_id = None
            p.known_accomplice_id = None


async def choose_solution_from_murderer_via_llm(
    *,
    players: list[PlayerState],
    rng: random.Random,
) -> Solution:
    """Ask the murderer agent to pick a solution pair (means+clue) from its dealt cards."""

    murderer = next((p for p in players if p.role == RoleName.murderer.value), None)
    if murderer is None:
        raise ValueError("No murderer in game")

    clue_ids = list(murderer.hand.clue_ids)
    means_ids = list(murderer.hand.means_ids)
    if not clue_ids or not means_ids:
        raise ValueError("Murderer has no cards")

    base = make_base_player_context(system_prefix="")
    player_ctx = PlayerContext(
        player_id=murderer.player_id,
        display_name=f"Seat {murderer.seat} (Murderer)",
        prompt="You are an AI player. Your cards are visible to others, but you cannot see them."
        " For this setup step, you are allowed to reason over the card IDs listed in the message.",
    )
    role_ctx = make_role_context(RoleName.murderer)
    ctx = compose_context(base=base, player=player_ctx, role=role_ctx)

    agent = create_default_agent(name=f"murderer-{murderer.player_id}")

    try:
        picked = await pick_solution_with_agent(agent=agent, ctx=ctx, clue_ids=clue_ids, means_ids=means_ids)
        return Solution(means_id=picked.means, clue_id=picked.clue)
    except SolutionPickError:
        # Fallback to deterministic-ish random pick so game can still be created.
        return Solution(means_id=rng.choice(means_ids), clue_id=rng.choice(clue_ids))


async def deal_hands(
    *,
    assets: GameAssets,
    players: list[PlayerState],
    rng: random.Random,
    hand_size: int = 4,
) -> None:
    """Deal 4 means + 4 clues to everyone except the forensic scientist.

    Mutates `players` in place.
    """

    # Deterministic shuffles from the seed.
    means_deck = [c.id for c in assets.means_cards.cards]
    clue_deck = [c.id for c in assets.clue_cards.cards]
    rng.shuffle(means_deck)
    rng.shuffle(clue_deck)

    def pop_n(deck: list[str], n: int) -> list[str]:
        if len(deck) < n:
            raise ValueError("Not enough cards in deck")
        out = deck[:n]
        del deck[:n]
        return out

    for p in players:
        # Default per-role flags.
        p.knows_solution = False
        p.solution = None
        p.knows_identities = False
        p.known_murderer_id = None
        p.known_accomplice_id = None
        if p.role == RoleName.investigator.value:
            p.has_badge = True

        if p.role == RoleName.forensic_scientist.value:
            p.hand = PlayerHand(means_ids=[], clue_ids=[])
            continue
        p.hand = PlayerHand(means_ids=pop_n(means_deck, hand_size), clue_ids=pop_n(clue_deck, hand_size))


# Back-compat wrapper used by older code paths/tests.
async def deal_hands_and_solution(
    *,
    assets: GameAssets,
    players: list[PlayerState],
    rng: random.Random,
    hand_size: int = 4,
) -> None:
    await deal_hands(assets=assets, players=players, rng=rng, hand_size=hand_size)
    # Old behavior: choose solution immediately.
    solution = await choose_solution_from_murderer_via_llm(players=players, rng=rng)
    dummy_state = GameState(
        game_id=__import__("uuid").UUID(int=0),
        num_ai_players=0,
        num_human_players=0,
        created_at=_now(),
        last_updated_at=_now(),
        seed=0,
        players=players,
    )
    apply_solution_and_secrets(state=dummy_state, solution=solution)


def describe_eyes_closed_sequence(*, has_witness: bool) -> list[str]:
    steps = [
        "Everyone, close your eyes.",
        "Murderer and Accomplice, open your eyes.",
        "Murderer, indicate the Key Evidence and Means of Murder.",
        "Murderer and Accomplice, close your eyes.",
    ]
    if has_witness:
        steps.extend(
            [
                "Witness, open your eyes.",
                "Forensic Scientist points to Murderer and Accomplice.",
                "Witness, close your eyes.",
            ]
        )
    steps.append("Everyone, open your eyes.")
    return steps

