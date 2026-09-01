const fallback = new Map<string, string>();
const tombstones = new Set<string>();
export const SESSION_WARNING = "Session persistence is unavailable; approval can continue only in this tab.";

export class SafeSessionStore {
  constructor(private readonly onWarning: (message: string) => void) {}

  get(key: string): string | null {
    if (tombstones.has(key)) return null;
    if (fallback.has(key)) return fallback.get(key) ?? null;
    try {
      return window.sessionStorage.getItem(key);
    } catch {
      this.onWarning(SESSION_WARNING);
      return fallback.get(key) ?? null;
    }
  }

  set(key: string, value: string): void {
    tombstones.delete(key);
    try {
      window.sessionStorage.setItem(key, value);
      fallback.delete(key);
    } catch {
      fallback.set(key, value);
      this.onWarning(SESSION_WARNING);
    }
  }

  remove(key: string): void {
    fallback.delete(key);
    tombstones.add(key);
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      this.onWarning(SESSION_WARNING);
    }
  }
}

export function resetSessionFallbackForTests(): void { fallback.clear(); tombstones.clear(); }
