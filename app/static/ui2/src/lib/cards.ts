import type { CardNameMaps, TileOptionsCsv } from './types';

const ASSETS_ROOT = '/ui-assets';

function parseCsv(text: string): Map<string, string> {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  const out = new Map<string, string>();
  for (let i = 1; i < lines.length; i++) {
    const row = lines[i];
    const idx = row.indexOf(',');
    if (idx === -1) continue;
    const id = row.slice(0, idx).trim();
    let name = row.slice(idx + 1).trim();
    if (name.startsWith('"') && name.endsWith('"')) name = name.slice(1, -1);
    if (id) out.set(id, name || id);
  }
  return out;
}

function parseTileOptionsCsv(text: string): TileOptionsCsv {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  const byId = new Map<string, { tile: string; option: string }>();
  const optionsByTile = new Map<string, { id: string; option: string }[]>();

  function splitRow(row: string): string[] {
    const out: string[] = [];
    let cur = '';
    let inQ = false;
    for (let i = 0; i < row.length; i++) {
      const ch = row[i];
      if (ch === '"') {
        inQ = !inQ;
        continue;
      }
      if (ch === ',' && !inQ) {
        out.push(cur.trim());
        cur = '';
        continue;
      }
      cur += ch;
    }
    out.push(cur.trim());
    return out;
  }

  for (let i = 1; i < lines.length; i++) {
    const cols = splitRow(lines[i]);
    if (cols.length < 3) continue;
    const id = cols[0];
    const tile = cols[1];
    const option = cols[2];
    if (!tile || !option) continue;

    if (id) byId.set(id, { tile, option });
    if (!optionsByTile.has(tile)) optionsByTile.set(tile, []);
    optionsByTile.get(tile)!.push({ id: id || option, option });
  }

  for (const [tile, opts] of optionsByTile.entries()) {
    opts.sort((a, b) => String(a.option).localeCompare(String(b.option)));
    optionsByTile.set(tile, opts);
  }

  return { byId, optionsByTile };
}

export async function loadCardNameMaps(): Promise<CardNameMaps> {
  const [meansCsv, clueCsv, lcdCsv, sceneCsv] = await Promise.all([
    fetch(`${ASSETS_ROOT}/means_cards.csv`).then((r) => r.text()),
    fetch(`${ASSETS_ROOT}/clue_cards.csv`).then((r) => r.text()),
    fetch(`${ASSETS_ROOT}/location_and_cause_of_death_tiles.csv`).then((r) => r.text()),
    fetch(`${ASSETS_ROOT}/scene_tiles.csv`).then((r) => r.text())
  ]);

  return {
    means: parseCsv(meansCsv),
    clues: parseCsv(clueCsv),
    lcd: parseTileOptionsCsv(lcdCsv),
    scene: parseTileOptionsCsv(sceneCsv)
  };
}

