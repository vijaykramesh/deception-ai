import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import sveltePreprocess from 'svelte-preprocess';
import path from 'node:path';

// Build output goes into app/static/ui2/dist so FastAPI can serve it at /ui2/.
// (Vite disallows outDir being the project root or a parent of root.)
export default defineConfig(() => {
  const base = '/ui2/';

  return {
    base,
    plugins: [
      svelte({
        preprocess: sveltePreprocess({
          typescript: true
        })
      })
    ],
    root: path.resolve(__dirname, 'src'),
    build: {
      outDir: path.resolve(__dirname, 'dist'),
      emptyOutDir: true,
      assetsDir: 'assets',
      sourcemap: true
    }
  };
});
