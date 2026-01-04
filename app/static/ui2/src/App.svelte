<script lang="ts">
  import './app.css';
  import Home from './routes/Home.svelte';
  import Game from './routes/Game.svelte';

  type Route = { name: 'home' } | { name: 'game'; gameId: string };

  function routeFromHash(): Route {
    const h = window.location.hash || '#/';
    const parts = h.replace('#', '').split('/').filter(Boolean);
    if (parts.length === 0) return { name: 'home' };
    if (parts[0] === 'game' && parts[1]) return { name: 'game', gameId: parts[1] };
    return { name: 'home' };
  }

  let route: Route = routeFromHash();

  function onHashChange() {
    route = routeFromHash();
  }

  window.addEventListener('hashchange', onHashChange);
</script>

<div class="wrap">
  {#if route.name === 'home'}
    <Home />
  {:else}
    <Game gameId={route.gameId} />
  {/if}
</div>
