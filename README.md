# deception-ai

Deception: *Murder in Hong Kong* — but built as a service where **multiple AI agents and human players** can play together.

This repo is in active scaffolding mode: the focus is building the service layer, persistent game state, and the core setup/dealing logic before full gameplay.

## What it currently does

- **FastAPI + Redis** service
  - `POST /game` creates a new game, persists it in Redis, and returns the full state.
  - `GET /game` lists games.
  - `GET /game/{game_id}` fetches a specific game.
- **Game setup logic**
  - Role dealing (4–12 players): Forensic Scientist, Murderer, Investigators (+ Accomplice + Witness for 6+).
  - Deals **4 clue cards** and **4 means cards** to each non–Forensic Scientist player.
  - Chooses the hidden solution from the **Murderer’s dealt cards**.
- **LLM integration (AG2/autogen)**
  - Uses an OpenAI-compatible API (e.g. **Ollama**) for LLM calls.
  - Supports **structured outputs** (JSON schema / `response_format`) for constrained responses.

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

- Unit tests run without external services.
- Integration tests that require Ollama are **env-gated** and will skip unless `OPENAI_BASE_URL` / `OPENAI_MODEL` are configured and reachable.

## License

This project is licensed under the MIT License — see [`LICENSE`](./LICENSE).
