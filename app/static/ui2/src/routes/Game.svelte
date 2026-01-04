<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api } from '../lib/api';
  import { loadCardNameMaps } from '../lib/cards';
  import type { CardNameMaps, GameState, Player, Pov } from '../lib/types';
  import { canSeeMurderSelections, canSeeMurdererRoles, getPov, setPov } from '../lib/pov';

  export let gameId: string;

  let state: GameState | null = null;
  let cardNames: CardNameMaps | null = null;

  let pov: Pov = getPov();
  let gameErr = '';

  // local UI state for this view
  let isRunAgentsPending = false;

  // Scroll-to-bottom behavior for the discussion log (mirrors old UI)
  let logEl: HTMLDivElement | null = null;
  let lastScrollAt = 0;
  $: if (logEl && state) {
    // Throttle: when state changes rapidly (ws events), avoid hammering layout every tick.
    const now = Date.now();
    if (now - lastScrollAt > 200) {
      lastScrollAt = now;
      Promise.resolve().then(() => {
        if (!logEl) return;
        logEl.scrollTop = logEl.scrollHeight;
      });
    }
  }

  const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws';

  function navigate(hash: string) {
    window.location.hash = hash;
  }

  function formatRole(role: string) {
    return role.replaceAll('_', ' ');
  }

  function roleTextForPlayer(p: Player): string {
    const isFs = p.role === 'forensic_scientist';
    if (isFs || pov === 'fs') return formatRole(p.role);
    if (
      canSeeMurdererRoles(pov) &&
      (p.role === 'murderer' || p.role === 'accomplice')
    )
      return formatRole(p.role);
    return 'unknown';
  }

  function roleClassForPlayer(p: Player): string {
    const rt = roleTextForPlayer(p);
    const cls = ['roleTag'];
    if (rt === 'unknown') cls.push('unknown');
    if ((p.role === 'murderer' || p.role === 'accomplice') && canSeeMurdererRoles(pov))
      cls.push('danger');
    if (p.role === 'witness' && pov === 'fs') cls.push('witness');
    return cls.join(' ');
  }

  function playersSorted(): Player[] {
    const ps = (state?.players || []).slice();
    ps.sort((a, b) => a.seat - b.seat);
    return ps;
  }

  function fsPlayer(): Player | undefined {
    return playersSorted().find((p) => p.role === 'forensic_scientist');
  }

  function nonFsPlayers(): Player[] {
    const ps = playersSorted();
    const fs = ps.find((p) => p.role === 'forensic_scientist');
    return ps.filter((p) => p !== fs);
  }

  function fsDefaultPosterId(): string {
    const fs = fsPlayer();
    return fs?.player_id || (state?.players?.[0]?.player_id ?? 'p1');
  }

  async function loadStateOnce() {
    state = await api<GameState>(`/game/${gameId}`);
  }

  async function runAgentsOnce() {
    if (isRunAgentsPending) return;
    gameErr = '';
    isRunAgentsPending = true;
    try {
      await api(`/games/${gameId}/agents/run_once?block_ms=10&count=10`, { method: 'POST' });
    } catch (e) {
      gameErr = (e as Error).message;
    } finally {
      isRunAgentsPending = false;
    }
  }

  // --- FS scene helpers (same behavior as /ui/)
  function lcdLocTile(): string | null {
    const locId = state?.fs_location_id || null;
    const lcdById = cardNames?.lcd.byId;
    return state?.fs_location_tile || (locId && lcdById?.get(locId)?.tile) || null;
  }

  function lcdCauseTile(): string | null {
    const causeId = state?.fs_cause_id || null;
    const lcdById = cardNames?.lcd.byId;
    return state?.fs_cause_tile || (causeId && lcdById?.get(causeId)?.tile) || null;
  }

  function locOptions() {
    const tile = lcdLocTile();
    return (tile && cardNames?.lcd.optionsByTile.get(tile)) || [];
  }

  function causeOptions() {
    const tile = lcdCauseTile();
    return (tile && cardNames?.lcd.optionsByTile.get(tile)) || [];
  }

  let selLoc: string | null = null;
  let selCause: string | null = null;
  let fsSceneErr = '';

  function ensureLocalSceneSelections() {
    // Mirror old UI: local selection vars default to server state
    if (!state) return;
    if (selLoc === null) selLoc = state.fs_location_id || null;
    if (selCause === null) selCause = state.fs_cause_id || null;
  }

  async function confirmScene() {
    fsSceneErr = '';
    if (!state) return;

    ensureLocalSceneSelections();

    if (!selLoc || !selCause) {
      fsSceneErr = 'Pick both a Location and a Cause of Death.';
      return;
    }

    try {
      await api(`/game/${state.game_id}/player/${encodeURIComponent(fsDefaultPosterId())}/fs_scene`, {
        method: 'POST',
        body: JSON.stringify({ location: selLoc, cause: selCause })
      });
    } catch (e) {
      fsSceneErr = (e as Error).message;
    }
  }

  // discussion
  let comment = '';

  async function sendComment() {
    if (!state) return;
    const text = comment.trim();
    if (!text) return;

    gameErr = '';
    try {
      await api(`/game/${state.game_id}/player/${encodeURIComponent(fsDefaultPosterId())}/discuss`, {
        method: 'POST',
        body: JSON.stringify({ comments: text })
      });
      comment = '';
    } catch (e) {
      gameErr = (e as Error).message;
    }
  }

  // polling fallback
  let pollTimer: number | null = null;
  function startPollingFallback() {
    if (pollTimer) return;
    pollTimer = window.setInterval(async () => {
      try {
        await loadStateOnce();
      } catch {
        // ignore
      }
    }, 1500);
  }

  let ws: WebSocket | null = null;
  let wsPingTimer: number | null = null;

  onMount(async () => {
    gameErr = '';

    try {
      await loadStateOnce();
    } catch (e) {
      gameErr = (e as Error).message;
      return;
    }

    try {
      cardNames = await loadCardNameMaps();
    } catch (e) {
      console.warn('Failed to load card name maps', e);
    }

    // Live updates via websocket (same behavior as /ui/)
    const wsUrl = `${wsProto}://${window.location.host}/ws/game/${gameId}`;
    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('WebSocket failed to construct:', e);
      startPollingFallback();
      return;
    }

    ws.onopen = () => {
      // Ensure we never create multiple ping loops.
      if (wsPingTimer) {
        window.clearInterval(wsPingTimer);
      }
      wsPingTimer = window.setInterval(() => {
        if (!ws) return;
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 20000);
    };

    ws.onmessage = async (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'game_updated') {
          await loadStateOnce();
          // clear pressed state on any successful update
          isRunAgentsPending = false;
        }
      } catch (e) {
        console.warn('ws message parse failed', e);
      }
    };

    ws.onerror = () => startPollingFallback();
    ws.onclose = () => startPollingFallback();

    window.setTimeout(() => {
      if (!ws) return;
      if (ws.readyState !== WebSocket.OPEN) startPollingFallback();
    }, 1200);

    const onResize = () => {
      // old UI rerendered on resize; Svelte does layout naturally.
      // Keep this hook to match behavior surface (noop).
    };

    window.addEventListener('resize', onResize);

    onDestroy(() => {
      window.removeEventListener('resize', onResize);
    });
  });

  onDestroy(() => {
    if (wsPingTimer) {
      window.clearInterval(wsPingTimer);
      wsPingTimer = null;
    }

    if (ws) {
      try {
        ws.close();
      } catch {
        // ignore
      }
      ws = null;
    }

    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  });

  function onPovChange(e: Event) {
    const next = (e.target as HTMLSelectElement).value as Pov;
    pov = next;
    setPov(next);
  }

  $: ensureLocalSceneSelections();
</script>

<div class="card" style="margin-bottom: 12px; padding: 12px 14px">
  <div class="row">
    <div style="font-size: 18px; font-weight: 750">Deception: AI</div>
    <div style="flex: 1"></div>
    <label class="muted" for="povSelect">POV</label>
    <select id="povSelect" style="min-width: 220px" bind:value={pov} on:change={onPovChange}>
      <option value="fs">Forensic Scientist</option>
      <option value="murderer">Murderer</option>
      <option value="witness">Witness</option>
      <option value="investigator">Investigator</option>
    </select>
  </div>

  {#if gameErr}
    <div id="gameErr" class="error" style="margin-top: 10px">{gameErr}</div>
  {:else}
    <div id="gameErr" class="error" style="margin-top: 10px"></div>
  {/if}
</div>

<div class="row" style="margin-bottom: 12px">
  <button on:click={() => navigate('#/')}>← Home</button>
  <div class="muted">Game:</div>
  <div style="font-weight: 600">{gameId}</div>
  <div style="flex: 1"></div>

  <button
    class:primary={!isRunAgentsPending}
    class:pressed={isRunAgentsPending}
    disabled={isRunAgentsPending}
    aria-pressed={isRunAgentsPending}
    aria-busy={isRunAgentsPending}
    on:click={runAgentsOnce}
  >
    {#if isRunAgentsPending}
      Running AI agents…
    {:else}
      Run AI agents once
    {/if}
  </button>
</div>

{#if !state}
  <div class="card">Loading…</div>
{:else}
  <div class="board">
    <div class="leftCol">
      <div class="card">
        <div class="title">
          <h1>Forensic Scientist</h1>
          <small class="muted">phase: {state.phase}</small>
        </div>

        {#if state.phase === 'setup_awaiting_fs_scene_pick' && fsPlayer()}
          <div class="scenePicker">
            <div class="muted">Set the scene (FS only)</div>

            <div class="card" style="background: var(--panel2); border-style: dashed;">
              <div style="font-weight: 650; margin-bottom: 6px">Pick Location</div>
              <div class="line"><span style="font-weight: 600">{lcdLocTile() || '—'}</span></div>

              <div class="tags">
                {#if !lcdLocTile()}
                  <span class="muted">Waiting for dealt tile…</span>
                {:else if locOptions().length === 0}
                  <span class="muted">No options found for tile.</span>
                {:else}
                  {#each locOptions() as o (o.id)}
                    <button class="tag tagBtn" class:selected={selLoc === o.id} title={o.id} on:click={() => (selLoc = o.id)}>
                      {o.option}
                    </button>
                  {/each}
                {/if}
              </div>
            </div>

            <div class="card" style="background: var(--panel2); border-style: dashed;">
              <div style="font-weight: 650; margin-bottom: 6px">Pick Cause of Death</div>
              <div class="line"><span style="font-weight: 600">{lcdCauseTile() || '—'}</span></div>

              <div class="tags">
                {#if !lcdCauseTile()}
                  <span class="muted">Waiting for dealt tile…</span>
                {:else if causeOptions().length === 0}
                  <span class="muted">No options found for tile.</span>
                {:else}
                  {#each causeOptions() as o (o.id)}
                    <button class="tag tagBtn" class:selected={selCause === o.id} title={o.id} on:click={() => (selCause = o.id)}>
                      {o.option}
                    </button>
                  {/each}
                {/if}
              </div>
            </div>

            <div class="row">
              <button class="primary" on:click={confirmScene}>Confirm scene</button>
            </div>

            {#if fsSceneErr}
              <div class="error" style="margin-top: 6px">{fsSceneErr}</div>
            {/if}
          </div>
        {:else}
          <!-- Scene compact -->
          <div class="card" style="background: var(--panel2); margin-top: 8px">
            <div style="font-weight: 650; margin-bottom: 6px">Scene</div>
            <div style="font-weight: 600; margin-top: 2px">{lcdLocTile() || '—'}</div>
            <div class="tags">
              {#each locOptions() as o (o.id)}
                <span class="tag" class:selected={state.fs_location_id === o.id} title={o.id}>{o.option}</span>
              {/each}
              {#if locOptions().length === 0}
                <span class="muted">—</span>
              {/if}
            </div>

            <div style="font-weight: 600; margin-top: 10px">{lcdCauseTile() || '—'}</div>
            <div class="tags">
              {#each causeOptions() as o (o.id)}
                <span class="tag" class:selected={state.fs_cause_id === o.id} title={o.id}>{o.option}</span>
              {/each}
              {#if causeOptions().length === 0}
                <span class="muted">—</span>
              {/if}
            </div>
          </div>
        {/if}

        <!-- Scene tiles + bullets compact -->
        <div class="card" style="background: var(--panel2); margin-top: 10px">
          <div style="font-weight: 650; margin-bottom: 6px">Scene tiles</div>
          {#if (state.fs_scene_tiles || []).length === 0}
            <div class="muted">Waiting for dealt scene tiles…</div>
          {:else}
            <div class="sceneCards">
              {#each (state.fs_scene_tiles || []).slice(0, 4) as tile (tile)}
                {@const opts = (tile && cardNames?.scene.optionsByTile.get(tile)) || []}
                {@const selected = (state.fs_scene_bullets && state.fs_scene_bullets[tile]) || null}
                <div class="card sceneCard">
                  <div style="font-weight: 600">{tile || '—'}</div>
                  <div class="tags">
                    {#each opts as o (o.id)}
                      <span class="tag" class:selected={selected && (o.id === selected || o.option === selected)} title={o.id}>
                        {o.option}
                      </span>
                    {/each}
                    {#if opts.length === 0}
                      <span class="muted">—</span>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      <!-- Discussion -->
      <div class="card discussion">
        <div class="title">
          <h1>Discussion</h1>
          <small class="muted">phase: {state.phase}</small>
        </div>

        <div class="log" bind:this={logEl}>
          {#each state.discussion || [] as m (m.created_at + ':' + m.player_id)}
            {@const p = state.players.find((pp) => pp.player_id === m.player_id)}
            {@const name = p?.display_name || m.player_id}
            <div class="msg">
              <div class="meta">
                <span>{name}</span>
                <span>{new Date(m.created_at).toLocaleString()}</span>
              </div>
              <div>{m.comments}</div>
            </div>
          {/each}
        </div>

        <div class="composer">
          <textarea bind:value={comment} placeholder="Say something to the table…"></textarea>
          <button class="primary" on:click={sendComment}>Send</button>
        </div>
      </div>
    </div>

    <!-- Players column -->
    <div class="rightCol">
      {#each nonFsPlayers() as p (p.player_id)}
        {@const display = p.display_name || p.player_id}
        {@const roleText = roleTextForPlayer(p)}
        {@const selectedMeans = canSeeMurderSelections(pov) ? state.solution?.means_id || null : null}
        {@const selectedClue = canSeeMurderSelections(pov) ? state.solution?.clue_id || null : null}

        <div class="card player">
          <header>
            <div>
              <div style="font-weight: 600">{display}</div>
              <div class="muted"><span class={roleClassForPlayer(p)}>{roleText}</span></div>
            </div>
            <span class="pill">{p.is_ai ? 'AI' : 'Human'}</span>
          </header>

          <div class="hand">
            <div class="line">
              <span class="muted">Means:</span>
              {#each p.hand?.means_ids || [] as id (id)}
                {@const name = cardNames?.means.get(id) || id}
                <span class="tag" class:selected={!!selectedMeans && id === selectedMeans && p.role === 'murderer'} title={id}>
                  {name}
                </span>
              {/each}
            </div>

            <div class="line">
              <span class="muted">Clues:</span>
              {#each p.hand?.clue_ids || [] as id (id)}
                {@const name = cardNames?.clues.get(id) || id}
                <span class="tag" class:selected={!!selectedClue && id === selectedClue && p.role === 'murderer'} title={id}>
                  {name}
                </span>
              {/each}
            </div>
          </div>
        </div>
      {/each}
    </div>
  </div>
{/if}
