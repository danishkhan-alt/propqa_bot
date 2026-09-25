/**
 * Secure-context-safe UUID generator.
 *
 * `crypto.randomUUID()` is only available in secure contexts (HTTPS or
 * `localhost`). When the app is served over plain HTTP (e.g. directly by
 * IP address in production), `crypto.randomUUID` is `undefined` and any
 * direct call to it throws, crashing React during init.
 *
 * This helper prefers the native implementation when available, falls back
 * to `crypto.getRandomValues()`-based UUID v4 generation, and finally falls
 * back to a `Math.random()`-based UUID v4 generator as a last resort.
 */
function uuidFromBytes(bytes: Uint8Array): string {
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
  return (
    hex.slice(0, 4).join("") +
    "-" +
    hex.slice(4, 6).join("") +
    "-" +
    hex.slice(6, 8).join("") +
    "-" +
    hex.slice(8, 10).join("") +
    "-" +
    hex.slice(10, 16).join("")
  );
}

function randomUUIDFallback(): string {
  const cryptoObj: Crypto | undefined = typeof crypto !== "undefined" ? crypto : undefined;

  if (cryptoObj?.getRandomValues) {
    const bytes = new Uint8Array(16);
    cryptoObj.getRandomValues(bytes);
    return uuidFromBytes(bytes);
  }

  const bytes = new Uint8Array(16);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = Math.floor(Math.random() * 256);
  }
  return uuidFromBytes(bytes);
}

export function randomUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      // Fall through to the fallback below (e.g. insecure context).
    }
  }
  return randomUUIDFallback();
}
