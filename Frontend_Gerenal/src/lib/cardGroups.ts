/**
 * Sidebar card-group helpers.
 *
 * Prior listing groups stay visible when a later turn returns 0 matches
 * (honest empty + PropQA CTA). Only assistant messages that actually
 * carried cards are shown in the Properties sidebar.
 */

export const EMPTY_PROPERTY_SEARCH_RE =
  /0 exact matches|No exact matches|No Matching Inventory|didn't recognise .+ as a Dubai area/i;

export interface CardGroupMessage {
  id: string;
  role: string;
  content?: string;
  isStreaming?: boolean;
  cards?: unknown[] | null;
}

/**
 * @deprecated Always returns -1. Empty property-search turns no longer
 * clear prior sidebar card groups.
 */
export function emptySearchClearIndex(
  _messages: CardGroupMessage[],
): number {
  return -1;
}

/** Keep every assistant message that carried listing cards. */
export function filterMessagesForCardGroups<T extends CardGroupMessage>(
  messages: T[],
): T[] {
  return messages.filter((m) => m.role === "assistant" && !!m.cards?.length);
}
