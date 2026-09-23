/**
 * LeadCaptureForm — Mode A buyer contact + email compose (HITL, callback, etc.).
 *
 * Wraps LeadInquiryEmailForm: buyer fields, PropQA From, Agent To, read-only body.
 */

import { useEffect, useState } from "react";
import { LeadInquiryEmailForm } from "./LeadInquiryEmailForm";
import type { PropertyContactContext } from "./PropertyContactSheet";
import { usePropertyContact } from "@/hooks/usePropertyContact";
import type { LeadSubmitData } from "./LeadActions";

export interface LeadCaptureField {
  name: string;
  label: string;
  type: "text" | "email" | "tel";
  required?: boolean;
}

export interface LeadCaptureHitlPayload {
  interrupt_id: string;
  task_id?: string;
  mode: "A";
  prompt?: string;
  fields: LeadCaptureField[];
  context_summary?: {
    search_summary?: string;
    matched_property_ids?: number[];
  };
}

interface LeadCaptureFormProps {
  payload: LeadCaptureHitlPayload;
  onSubmit: (data: LeadSubmitData) => Promise<void> | void;
  onDismiss?: () => void;
  className?: string;
  variant?: "default" | "sheet";
  /** When known (e.g. PropertyContactSheet), skip contact fetch. */
  agentEmail?: string | null;
  agentName?: string | null;
  sessionId?: string;
  listingContext?: Partial<PropertyContactContext>;
}

export function LeadCaptureForm({
  payload,
  onSubmit,
  onDismiss,
  className,
  variant = "default",
  agentEmail: agentEmailProp,
  agentName: agentNameProp,
  sessionId,
  listingContext,
}: LeadCaptureFormProps) {
  const { fetchContact } = usePropertyContact();
  const propertyIds = payload.context_summary?.matched_property_ids ?? [];
  const primaryId = propertyIds[0] ?? listingContext?.propertyId ?? 0;

  const [agentEmail, setAgentEmail] = useState<string | null>(agentEmailProp ?? null);
  const [agentName, setAgentName] = useState<string | null>(agentNameProp ?? null);

  useEffect(() => {
    setAgentEmail(agentEmailProp ?? null);
    setAgentName(agentNameProp ?? null);
  }, [agentEmailProp, agentNameProp]);

  useEffect(() => {
    if (agentEmailProp != null || !primaryId) return;
    let cancelled = false;
    void fetchContact(primaryId).then((c) => {
      if (cancelled || !c) return;
      setAgentEmail((prev) => prev ?? c.email ?? null);
      setAgentName((prev) => prev ?? c.agent_name ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [primaryId, agentEmailProp, fetchContact]);

  const context: PropertyContactContext = {
    propertyId: listingContext?.propertyId ?? primaryId,
    propertyIds: listingContext?.propertyIds ?? propertyIds,
    propertyTitle:
      listingContext?.propertyTitle
      ?? payload.context_summary?.search_summary
      ?? "Property inquiry",
    price: listingContext?.price ?? null,
    propqaUrl: listingContext?.propqaUrl ?? null,
  };

  const resolvedIds =
    propertyIds.length > 0
      ? propertyIds
      : listingContext?.propertyIds?.length
        ? listingContext.propertyIds
        : primaryId
          ? [primaryId]
          : [];

  const contextLabel: "listing" | "search" =
    listingContext?.propertyId ? "listing" : "search";

  return (
    <LeadInquiryEmailForm
      variant={variant}
      className={className}
      contextLabel={contextLabel}
      submitLabel={variant === "sheet" ? "Send inquiry via PropQA" : "Connect me with an agent"}
      context={context}
      propertyIds={resolvedIds}
      agentEmail={agentEmail}
      agentName={agentName}
      sessionId={sessionId}
      prompt={payload.prompt ?? "Send your details to the listing contact"}
      onDismiss={onDismiss}
      onSubmit={async (data) => {
        await onSubmit({
          buyer_name: data.buyer_name,
          buyer_email: data.buyer_email,
          buyer_phone: data.buyer_phone,
          property_ids: data.property_ids.length ? data.property_ids : resolvedIds,
          from_email: data.from_email,
          to_email: data.to_email,
          message_override: data.message_override,
          message_html_override: data.message_html_override,
          ui_surface: "lead_capture_form",
        });
      }}
    />
  );
}
