import "@testing-library/jest-dom";

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, val: string) => { store[key] = val; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// Mock crypto.randomUUID
Object.defineProperty(globalThis, "crypto", {
  value: {
    randomUUID: () => "test-uuid-1234-5678-9012",
    getRandomValues: (arr: Uint8Array) => arr.fill(1),
  },
});

// Silence sonner toasts in tests
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).__vitest_mock__ = true;
