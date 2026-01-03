# deception-ai

Deception: *Murder in Hong Kong* — built as a service where **multiple AI agents and human players** can play together.

This repo is intentionally service-first: the core focus is a clean control flow for turns/actions, persistent state, and an architecture that supports **humans + agents going through the same API surface**.

## What it currently does

### Working gameplay scaffolding (setup → discussion → completed)

- **Game creation + setup (4–12 players)**
  - Deals roles: **Forensic Scientist**, **Murderer**, **Investigators** (+ **Accomplice** + **Witness** for 6+ players).
  - Deals hands:
    - Every non–Forensic Scientist gets **4 clue cards** + **4 means cards**.
  - Game starts in phase: `setup_awaiting_murder_pick`.

- **Setup actions (implemented end-to-end through the dispatcher)**
  - **Murderer picks solution** (must pick from their dealt hand)
    - Phase: `setup_awaiting_murder_pick` → `setup_awaiting_fs_scene_pick`
  - **Forensic Scientist picks public scene** (location + cause of death option IDs)
    - Phase: `setup_awaiting_fs_scene_pick` → `discussion`

- **Discussion + solve (basic scaffolding)**
  - Anyone can add discussion comments (until completed).
  - Investigators can submit a solve guess during discussion.
    - Wrong guess consumes their badge.
    - Correct guess ends the game: phase → `completed`.

### Service + architecture

- **FastAPI + Redis**
  - Game state is persisted as JSON in Redis.
  - Per-game locking prevents concurrent mutation races.

- **Finite State Machine (FSM) as phase vocabulary**
  - `app.fsm.GameFSM` defines the core phase progression:
    - `setup_awaiting_murder_pick` → `setup_awaiting_fs_scene_pick` → `discussion` → `completed`
  - The FSM is used as a **guardrail and vocabulary** for legal transitions.

- **Action dispatcher (single control flow)**
  - `app.actions.dispatch_action_async(...)`
  - Every “turn message” (from a human UI or an agent) goes through the same flow:

    **message in → validate → apply domain update → persist → publish events**

  - The dispatcher emits structured logs for:
    - `action_received`
    - `action_validated`
    - `phase_transition`
    - `action_applied`
    - `action_finished`

- **Validator pipeline (extensible legality checks)**
  - `app.turn_processing.validators` defines a composable pipeline per action.
  - Current validators:
    - **PhaseValidator** (action only allowed in specific phases)
    - **RoleValidator** (action only allowed for specific roles)
    - **CompletedGameValidator** (blocks actions after completion)
  - This is the intended home for future checks: per-turn ordering, rate limiting, idempotency, etc.

- **Mailbox / outbox style events (Redis Streams)**
  - After state changes, the dispatcher publishes mailbox messages to per-player streams.
  - Examples:
    - `prompt_murder_pick`
    - `prompt_fs_scene_pick`
    - `state_changed`

### AI agent integration

- **LLM integration (AG2/autogen)**
  - Uses an OpenAI-compatible API (e.g. **Ollama**) for LLM calls.
  - Supports **structured outputs** (JSON schema / `response_format`) for constrained responses.

- **Agent runner is API-driven**
  - The agent runner consumes mailbox prompts and submits actions via the same dispatcher.
  - Dev endpoint:
    - `POST /games/{game_id}/agents/run_once`

## API overview

### Typed action endpoints

- Create game:
  - `POST /game`
- Fetch/list games:
  - `GET /game`
  - `GET /game/{game_id}`
- Typed per-action endpoints:
  - `POST /game/{game_id}/player/{player_id}/murder`
  - `POST /game/{game_id}/player/{player_id}/fs_scene`
  - `POST /game/{game_id}/player/{player_id}/discuss`
  - `POST /game/{game_id}/player/{player_id}/solve`

### Typed generic action endpoint (dev/test convenience)

- `POST /games/{game_id}/actions`

Body is a discriminated union on the `action` field, e.g.

- `{"action": "murder", "player_id": "p1", "clue": "...", "means": "..."}`
- `{"action": "fs_scene", "player_id": "p2", "location": "...", "cause": "..."}`

### Debug endpoints

- Mailbox stream read:
  - `GET /games/{game_id}/players/{player_id}/mailbox`

## Local development

### Configuration (.env)

This project reads configuration from environment variables.

1) Copy the template:

```bash
cp env.example .env
```

2) Edit `.env` to match your setup.

Notes:
- For **local runs** (running the API directly on your machine), `REDIS_URL` should usually be:
  - `redis://localhost:6379/0`
- For **Docker Compose**, the API container automatically overrides `REDIS_URL` to talk to the `redis` service.
  You can leave the template value intact.

### Prereqs

- Python (see `pyproject.toml` for the supported version range)
- Redis (via Docker is easiest)
- Optional: Ollama for local LLM calls

### Run Redis + API (Docker Compose)

This repo includes a `docker-compose.yml` with Redis and the API container.

The compose file loads `.env` automatically.

### Run against Ollama (recommended)

Start Ollama:

```bash
ollama serve
```

Pull the model (example):

```bash
ollama pull gpt-oss:20b
```

Edit `.env` to point at the OpenAI-compatible endpoint:

- `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`
- `OPENAI_MODEL=gpt-oss:20b`
- `OPENAI_API_KEY=ollama`

## Tests

### Run unit tests

```bash
pytest
```

### Run tests with coverage + Cobertura report

```bash
./scripts/coverage.sh
```

Outputs:
- `coverage.xml` (Cobertura XML)
- `htmlcov/` (HTML report)

Note: install dev dependencies first:

```bash
uv sync --extra dev
```

### Integration tests

Integration tests that require Ollama are **env-gated** and will skip unless `OPENAI_BASE_URL` / `OPENAI_MODEL` are configured and reachable.

## License

This project is licensed under the MIT License — see [`LICENSE`](./LICENSE).
