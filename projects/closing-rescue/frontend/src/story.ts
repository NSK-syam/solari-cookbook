export interface PersistedStoryEvent {
  id: string;
  case_id: string;
  event_type: string;
  chapter: number;
  message: string;
  data: Array<{ key: string; value_json: string }>;
  created_at: string;
}

export interface StorySnapshot {
  visibleChapter: number;
  persistedChapter: number;
  paused: boolean;
  replaying: boolean;
  skipped: boolean;
  eventIds: string[];
  visibleEventIds: string[];
}

export function deriveChapter(events: readonly PersistedStoryEvent[]): number {
  return events.reduce((latest, event) => Math.max(latest, clampChapter(event.chapter)), 1);
}

function clampChapter(chapter: number): number {
  return Math.max(1, Math.min(6, Number.isFinite(chapter) ? Math.trunc(chapter) : 1));
}

function canonicalEvents(events: readonly PersistedStoryEvent[]): PersistedStoryEvent[] {
  const seen = new Set<string>();
  return events.filter((event) => {
    if (seen.has(event.id)) return false;
    seen.add(event.id);
    return true;
  });
}

export class StoryController {
  private events: PersistedStoryEvent[];
  private visibleEventCount: number;
  private paused = false;
  private replaying = false;
  private skipped = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private listeners = new Set<(snapshot: StorySnapshot) => void>();
  private readonly delayMs: number;

  constructor(events: readonly PersistedStoryEvent[], options: { startAtBeginning?: boolean; delayMs?: number } = {}) {
    this.events = canonicalEvents(events);
    this.visibleEventCount = options.startAtBeginning ? Math.min(1, this.events.length) : this.events.length;
    this.replaying = options.startAtBeginning === true;
    this.delayMs = Math.max(0, options.delayMs ?? 1800);
    this.schedule();
  }

  snapshot(): StorySnapshot {
    const persistedChapter = deriveChapter(this.events);
    const visibleChapter = this.visibleEventCount === 0 ? 1 : clampChapter(this.events[this.visibleEventCount - 1].chapter);
    return {
      visibleChapter,
      persistedChapter,
      paused: this.paused,
      replaying: this.replaying,
      skipped: this.skipped,
      eventIds: this.events.map((event) => event.id),
      visibleEventIds: this.events.slice(0, this.visibleEventCount).map((event) => event.id)
    };
  }

  subscribe(listener: (snapshot: StorySnapshot) => void): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  sync(events: readonly PersistedStoryEvent[]): void {
    const byId = new Map(this.events.map((event) => [event.id, event]));
    let latestChapter = this.events.at(-1)?.chapter ?? 1;
    for (const event of events) {
      if (byId.has(event.id)) continue;
      if (event.chapter < latestChapter) throw new Error("Persisted story order cannot move backward");
      byId.set(event.id, event);
      latestChapter = event.chapter;
    }
    this.events = [...byId.values()];
    this.emit();
    this.schedule();
  }

  pause(): void { this.paused = true; this.clearTimer(); this.emit(); }
  resume(): void { this.paused = false; this.emit(); this.schedule(); }
  replay(): void { this.visibleEventCount = Math.min(1, this.events.length); this.paused = false; this.replaying = true; this.skipped = false; this.emit(); this.schedule(); }
  skipToResult(): void { this.visibleEventCount = this.events.length; this.replaying = false; this.skipped = true; this.clearTimer(); this.emit(); }
  dispose(): void { this.clearTimer(); this.listeners.clear(); }

  private schedule(): void {
    this.clearTimer();
    if (this.paused) return;
    if (this.visibleEventCount >= this.events.length) { this.replaying = false; return; }
    this.timer = setTimeout(() => {
      this.visibleEventCount += 1;
      this.emit();
      this.schedule();
    }, this.delayMs);
  }

  private clearTimer(): void { if (this.timer !== null) clearTimeout(this.timer); this.timer = null; }
  private emit(): void { const snapshot = this.snapshot(); for (const listener of this.listeners) listener(snapshot); }
}
