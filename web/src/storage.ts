export type Role = 'parent' | 'baby';

export interface Prefs {
  role: Role;
  name: string;
}

const KEY = 'babycue.prefs';
export const DEFAULT_PREFS: Prefs = { role: 'parent', name: '' };

export function loadPrefs(): Prefs {
  try {
    const data = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<Prefs> | null;
    return {
      role: data?.role === 'baby' ? 'baby' : 'parent',
      name: typeof data?.name === 'string' ? data.name : '',
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: Prefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Remembering the settings is a convenience; the app works without it.
  }
}

/** What the screens call the baby when no name was entered. */
export function babyName(name: string): string {
  return name.trim() || 'Baby';
}
