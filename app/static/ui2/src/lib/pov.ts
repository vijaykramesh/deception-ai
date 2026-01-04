import type { Pov } from './types';

export function povLabel(pov: Pov): string {
  if (pov === 'fs') return 'Forensic Scientist';
  if (pov === 'murderer') return 'Murderer';
  if (pov === 'witness') return 'Witness';
  if (pov === 'investigator') return 'Investigator';
  return 'Forensic Scientist';
}

export function getPov(): Pov {
  return ((globalThis as any).__POV__ || localStorage.getItem('deception:pov') || 'fs') as Pov;
}

export function setPov(pov: Pov): void {
  (globalThis as any).__POV__ = pov;
  localStorage.setItem('deception:pov', pov);
}

export function canSeeMurdererRoles(pov: Pov): boolean {
  return pov === 'fs' || pov === 'murderer' || pov === 'witness';
}

export function canSeeMurderSelections(pov: Pov): boolean {
  return pov === 'fs' || pov === 'murderer' || pov === 'accomplice';
}

