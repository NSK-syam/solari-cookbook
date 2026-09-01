import { describe, expect, test, vi } from "vitest";
import { StoryController, deriveChapter, type PersistedStoryEvent } from "./story";

function event(chapter: number, id = `evt-${chapter}`): PersistedStoryEvent {
  return {
    id,
    case_id: "case-1",
    event_type: chapter === 4 ? "contradiction.detected" : `chapter.${chapter}`,
    chapter,
    message: `Chapter ${chapter}`,
    data: [{ key: "chapter", value_json: String(chapter) }],
    created_at: `2026-08-05T14:0${chapter}:00Z`
  };
}

describe("Closing Rescue story controller", () => {
  test("derives the chapter only from persisted events", () => {
    expect(deriveChapter([event(1), event(4)])).toBe(4);
    expect(deriveChapter([])).toBe(1);
  });

  test("a fresh journey reveals persisted chapters without inventing events", () => {
    vi.useFakeTimers();
    const controller = new StoryController([event(1), event(2), event(4)], {
      startAtBeginning: true,
      delayMs: 100
    });
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 1, persistedChapter: 4 });
    vi.advanceTimersByTime(100);
    expect(controller.snapshot().visibleChapter).toBe(2);
    vi.advanceTimersByTime(100);
    expect(controller.snapshot().visibleChapter).toBe(4);
    expect(controller.snapshot().visibleEventIds).toEqual(["evt-1", "evt-2", "evt-4"]);
    controller.dispose();
    vi.useRealTimers();
  });

  test("pause, resume, replay, and skip affect presentation only", () => {
    vi.useFakeTimers();
    const events = [event(1), event(2), event(3), event(4), event(5), event(6)];
    const controller = new StoryController(events, { startAtBeginning: true, delayMs: 100 });
    controller.pause();
    vi.advanceTimersByTime(500);
    expect(controller.snapshot().visibleChapter).toBe(1);
    controller.resume();
    vi.advanceTimersByTime(100);
    expect(controller.snapshot().visibleChapter).toBe(2);
    controller.skipToResult();
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 6, persistedChapter: 6 });
    controller.replay();
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 1, persistedChapter: 6 });
    controller.dispose();
    vi.useRealTimers();
  });

  test("repeated evidence events are revealed one at a time without changing chapter", () => {
    vi.useFakeTimers();
    const controller = new StoryController([event(1), event(2), event(3, "mireye"), event(3, "permit"), event(3, "noaa"), event(4)], { startAtBeginning: true, delayMs: 50 });
    vi.advanceTimersByTime(150);
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 3, visibleEventIds: ["evt-1", "evt-2", "mireye", "permit"] });
    vi.advanceTimersByTime(50);
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 3, visibleEventIds: ["evt-1", "evt-2", "mireye", "permit", "noaa"] });
    controller.dispose();
    vi.useRealTimers();
  });

  test("reload reconstructs the latest persisted chapter", () => {
    const controller = new StoryController([event(1), event(4), event(6)]);
    expect(controller.snapshot()).toMatchObject({ visibleChapter: 6, persistedChapter: 6 });
    controller.dispose();
  });

  test("sync ignores duplicate events and never moves persisted state backwards", () => {
    const controller = new StoryController([event(1), event(4)]);
    controller.sync([event(1), event(4), event(4)]);
    controller.sync([event(1)]);
    expect(controller.snapshot().persistedChapter).toBe(4);
    expect(controller.snapshot().eventIds).toEqual(["evt-1", "evt-4"]);
    controller.dispose();
  });

  test("sync rejects a newly appended event that moves persisted order backwards", () => {
    const controller = new StoryController([event(1), event(4)]);
    expect(() => controller.sync([event(3, "late-evidence")])).toThrow(/backward/i);
    expect(controller.snapshot()).toMatchObject({ persistedChapter: 4, eventIds: ["evt-1", "evt-4"] });
    controller.dispose();
  });
});
