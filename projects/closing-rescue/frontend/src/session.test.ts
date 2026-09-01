import { afterEach, describe, expect, test, vi } from "vitest";
import { SafeSessionStore, resetSessionFallbackForTests } from "./session";

describe("safe session storage", () => {
  afterEach(() => { vi.restoreAllMocks(); resetSessionFallbackForTests(); });

  test("falls back in memory when writes and reads throw", () => {
    const warning = vi.fn();
    const store = new SafeSessionStore(warning);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });
    store.set("approval", "secret");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("denied"); });
    expect(store.get("approval")).toBe("secret");
    expect(warning).toHaveBeenCalledWith(expect.stringMatching(/only in this tab/i));
  });

  test("remove is nonfatal and clears the memory fallback when storage throws", () => {
    const store = new SafeSessionStore(vi.fn());
    store.set("approval", "secret");
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("denied"); });
    expect(() => store.remove("approval")).not.toThrow();
    expect(store.get("approval")).toBeNull();
  });

  test("failed overwrite makes the newer in-memory value authoritative over stale storage", () => {
    const store = new SafeSessionStore(vi.fn());
    sessionStorage.setItem("approval", "old-secret");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });
    store.set("approval", "rotated-secret");
    vi.restoreAllMocks();
    expect(sessionStorage.getItem("approval")).toBe("old-secret");
    expect(store.get("approval")).toBe("rotated-secret");
  });
});
