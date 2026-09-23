/**
 * usePropertyContact — fetch and cache per-property listing contact (agency-first).
 */

import { useCallback, useRef, useState } from "react";

export type ContactSource = "agency" | "listing_agent";

export interface PropertyContact {
  property_id: number;
  agent_id: number;
  agent_name: string;
  company_name?: string | null;
  phone?: string | null;
  mobile?: string | null;
  whatsapp?: string | null;
  email?: string | null;
  verification_status: string;
  contact_source: ContactSource;
}

const cache = new Map<number, PropertyContact>();

/** Map Mode B agent payload to the same shape as property-contact API. */
export function contactFromAgent(
  agent: {
    agent_id: number;
    agent_name: string;
    company_name?: string | null;
    phone?: string | null;
    mobile?: string | null;
    whatsapp?: string | null;
    email?: string | null;
    verification_status: string;
  },
  propertyId: number,
): PropertyContact {
  return {
    property_id: propertyId,
    agent_id: agent.agent_id,
    agent_name: agent.agent_name,
    company_name: agent.company_name,
    phone: agent.phone,
    mobile: agent.mobile,
    whatsapp: agent.whatsapp,
    email: agent.email,
    verification_status: agent.verification_status,
    contact_source: "listing_agent",
  };
}

export function usePropertyContact() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<Map<number, Promise<PropertyContact | null>>>(new Map());

  const fetchContact = useCallback(async (propertyId: number): Promise<PropertyContact | null> => {
    const cached = cache.get(propertyId);
    if (cached) return cached;

    let pending = inflight.current.get(propertyId);
    if (!pending) {
      pending = (async () => {
        setLoading(true);
        setError(null);
        try {
          const res = await fetch(
            `/api/leads/property-contact?property_id=${encodeURIComponent(String(propertyId))}`,
          );
          if (!res.ok) {
            if (res.status === 404) {
              setError("No contact available for this listing.");
              return null;
            }
            throw new Error(`HTTP ${res.status}`);
          }
          const data = (await res.json()) as { contact: PropertyContact };
          const contact = data.contact;
          if (contact) cache.set(propertyId, contact);
          return contact ?? null;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : "Unknown error";
          setError(msg);
          return null;
        } finally {
          setLoading(false);
          inflight.current.delete(propertyId);
        }
      })();
      inflight.current.set(propertyId, pending);
    }

    return pending;
  }, []);

  const recordCtaClick = useCallback(
    async (
      propertyId: number,
      channel: "phone" | "whatsapp" | "email",
      sessionId: string,
      options?: { ui_surface?: string; turn_id?: string | null },
    ): Promise<void> => {
      if (!sessionId) return;
      try {
        await fetch("/api/leads/cta-click", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            property_id: propertyId,
            channel,
            session_id: sessionId,
            ui_surface: options?.ui_surface,
            turn_id: options?.turn_id ?? undefined,
          }),
        });
      } catch {
        // Analytics only — non-blocking
      }
    },
    [],
  );

  return { fetchContact, recordCtaClick, loading, error, clearError: () => setError(null) };
}
