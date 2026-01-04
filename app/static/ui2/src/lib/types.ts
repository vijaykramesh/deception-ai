export type Pov = 'fs' | 'murderer' | 'witness' | 'investigator' | 'accomplice';

export type GamePhase =
  | 'setup_awaiting_murder_pick'
  | 'setup_awaiting_fs_scene_pick'
  | 'discussion'
  | 'completed'
  | string;

export interface PlayerHand {
  means_ids: string[];
  clue_ids: string[];
}

export interface Player {
  player_id: string;
  display_name?: string | null;
  seat: number;
  role: string;
  is_ai: boolean;
  hand?: PlayerHand | null;
}

export interface DiscussionMessage {
  player_id: string;
  comments: string;
  created_at: string;
}

export interface Solution {
  means_id?: string | null;
  clue_id?: string | null;
}

export interface GameState {
  game_id: string;
  phase: GamePhase;
  players: Player[];
  discussion?: DiscussionMessage[];
  solution?: Solution | null;

  // FS scene pick
  fs_location_id?: string | null;
  fs_cause_id?: string | null;
  fs_location_tile?: string | null;
  fs_cause_tile?: string | null;

  // Scene tiles + bullets
  fs_scene_tiles?: string[];
  fs_scene_bullets?: Record<string, string>;
}

export interface TileOption {
  id: string;
  option: string;
}

export interface TileOptionsCsv {
  byId: Map<string, { tile: string; option: string }>;
  optionsByTile: Map<string, TileOption[]>;
}

export interface CardNameMaps {
  means: Map<string, string>;
  clues: Map<string, string>;
  lcd: TileOptionsCsv;
  scene: TileOptionsCsv;
}

