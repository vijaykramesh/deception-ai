from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.base import AgentAction
from app.contexts import make_base_player_context
from app.core.context import BaseAgentContext, compose_context
from app.core.events import GameEvent
from app.players import PlayerSpec


@dataclass(slots=True)
class GameState:
    turn_id: int = 0
    history: list[GameEvent] = field(default_factory=list)


async def run_single_turn(*, state: GameState, base: BaseAgentContext, players: list[PlayerSpec]) -> list[GameEvent]:
    turn_id = state.turn_id
    events: list[GameEvent] = []

    base = make_base_player_context(system_prefix=base.system_prompt)

    events.append(GameEvent.now(type="TURN_STARTED", turn_id=turn_id, payload={"n": len(players)}))

    for spec in players:
        rendered = compose_context(base=base, player=spec.player, role=spec.role)
        action: AgentAction = await spec.agent.propose_action(
            prompt="Do a tiny warmup: summarize your role in one sentence.",
            ctx=rendered,
        )
        events.append(
            GameEvent.now(
                type="ACTION_PROPOSED",
                turn_id=turn_id,
                payload={"agent": spec.agent.name, "role": spec.role.role_name, "content": action.content},
            )
        )
        # For now, committing == appending to history.
        events.append(
            GameEvent.now(
                type="ACTION_COMMITTED",
                turn_id=turn_id,
                payload={"agent": spec.agent.name, "kind": action.kind},
            )
        )

    events.append(GameEvent.now(type="TURN_ENDED", turn_id=turn_id, payload={}))

    state.history.extend(events)
    state.turn_id += 1
    return events
