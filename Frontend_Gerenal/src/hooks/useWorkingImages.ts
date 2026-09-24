import { useCallback, useMemo, useState } from "react";

/**
 * Listing photos minus any that failed to load, so a dead URL never shows a broken
 * icon: the carousel skips it, and a card with none left falls back to "No image".
 */
export function useWorkingImages(urls: string[]) {
  const [failed, setFailed] = useState<ReadonlySet<string>>(() => new Set());
  const images = useMemo(() => urls.filter((url) => !failed.has(url)), [urls, failed]);
  const markFailed = useCallback((url: string) => {
    setFailed((prev) => (prev.has(url) ? prev : new Set(prev).add(url)));
  }, []);
  return { images, markFailed };
}
