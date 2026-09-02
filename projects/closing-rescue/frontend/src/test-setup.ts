import "@testing-library/jest-dom/vitest";

// Node 26 exposes experimental global Web Storage objects. Vitest preserves
// those globals instead of installing jsdom's implementations, which makes
// browser-storage tests exercise a different object than the application.
// Pin the globals to this test environment's jsdom storage objects.
const jsdomLocalStorage = window.localStorage;
const jsdomSessionStorage = window.sessionStorage;
const JsdomStorage = Object.getPrototypeOf(jsdomSessionStorage).constructor;

Object.defineProperties(globalThis, {
  localStorage: { configurable: true, value: jsdomLocalStorage },
  sessionStorage: { configurable: true, value: jsdomSessionStorage },
  Storage: { configurable: true, value: JsdomStorage }
});
