<script lang="ts">
  import { api } from '../lib/api';
  import type { GameState } from '../lib/types';

  let joinGameId = '';

  let numAi = 4;
  let numHuman = 0;
  let err = '';

  function navigate(hash: string) {
    window.location.hash = hash;
  }

  async function createGame() {
    err = '';
    try {
      const state = await api<GameState>('/game', {
        method: 'POST',
        body: JSON.stringify({ num_ai_players: numAi, num_human_players: numHuman })
      });
      navigate(`#/game/${state.game_id}`);
    } catch (e) {
      err = (e as Error).message;
    }
  }

  function join() {
    const id = joinGameId.trim();
    if (!id) return;
    navigate(`#/game/${id}`);
  }
</script>

<div class="card">
  <div class="title">
    <h1>deception-ai</h1>
    <small class="muted">Minimal local UI (websocket updates)</small>
  </div>
  <p class="muted">Join an existing game by ID, or create a new one.</p>

  <div class="row">
    <input bind:value={joinGameId} placeholder="game id (UUID)" style="min-width: 340px" />
    <button class="primary" on:click={join}>Join</button>
  </div>
</div>

<div class="card" style="margin-top: 12px">
  <div class="title">
    <h1>Create new game</h1>
    <small class="muted">4–12 total players supported by rules</small>
  </div>

  <div class="row" style="margin-top: 10px">
    <label class="muted" for="numAi">AI players</label>
    <input id="numAi" type="number" min="0" max="12" bind:value={numAi} style="width: 90px" />

    <label class="muted" for="numHuman">Human players</label>
    <input id="numHuman" type="number" min="0" max="12" bind:value={numHuman} style="width: 90px" />

    <button class="primary" on:click={createGame}>Create</button>
  </div>

  {#if err}
    <div class="error" style="margin-top: 10px">{err}</div>
  {/if}
</div>
