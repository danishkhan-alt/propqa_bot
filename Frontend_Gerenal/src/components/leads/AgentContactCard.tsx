/**
 * AgentContactCard — Mode B direct-contact display.
 *
 * CTA buttons open the same PropertyContactSheet flows as sidebar listing cards.
 */

import { useState } from "react";
import { ChevronDown, ChevronUp, BadgeCheck, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ContactCtaIconRow } from "./ContactCtaIconRow";
import {
  PropertyContactSheet,
  type CtaChannel,
  type PropertyContactContext,
} from "./PropertyContactSheet";
import { contactFromAgent } from "@/hooks/usePropertyContact";
import type { PropertyContact } from "@/hooks/usePropertyContact";

export interface AgentContact {
  agent_id: number;
  agent_name: string;
  company_name?: string | null;
  phone?: string | null;
  mobile?: string | null;
  whatsapp?: string | null;
  email?: string | null;
  verification_status: string;
  experience_years?: number | null;
  specialization_areas?: string[];
  property_ids?: number[];
}

export interface AgentCoverage {
  requested_count: number;
  resolved_count: number;
  unresolved_property_ids: number[];
}

interface AgentContactCardProps {
  agent: AgentContact;
  sessionId: string;
  searchSummary?: string;
  fallbackPropertyIds: number[];
  propertyTitles?: Record<number, string>;
  onSubmitLead: (data: {
    buyer_name: string;
    buyer_email: string;
    buyer_phone: string;
    property_ids: number[];
  }) => Promise<void>;
  className?: string;
}

function listingLabel(propertyId: number, titles?: Record<number, string>): string {
  return titles?.[propertyId]?.trim() || `Property #${propertyId}`;
}

export function AgentContactCard({
  agent,
  sessionId,
  searchSummary,
  fallbackPropertyIds,
  propertyTitles,
  onSubmitLead,
  className,
}: AgentContactCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetChannel, setSheetChannel] = useState<CtaChannel | null>(null);
  const [sheetContext, setSheetContext] = useState<PropertyContactContext | null>(null);
  const [preloaded, setPreloaded] = useState<PropertyContact | null>(null);

  const isApproved = agent.verification_status === "approved";
  const areas = agent.specialization_areas?.slice(0, 3) ?? [];
  const propertyIds =
    agent.property_ids?.length ? agent.property_ids : fallbackPropertyIds;
  const primaryPropertyId = propertyIds[0];
  const subjectLabel = agent.agent_name;
  const listingCount = propertyIds.length;
  const canExpand = listingCount > 0 || areas.length > 0;

  function openCta(channel: CtaChannel) {
    if (!primaryPropertyId) return;
    const title =
      searchSummary?.trim() ||
      (agent.company_name
        ? `${agent.agent_name} — ${agent.company_name}`
        : agent.agent_name);
    setSheetContext({
      propertyId: primaryPropertyId,
      propertyIds,
      propertyTitle: title,
    });
    setPreloaded(contactFromAgent(agent, primaryPropertyId));
    setSheetChannel(channel);
    setSheetOpen(true);
  }

  return (
    <>
      <div
        className={cn(
          "overflow-hidden rounded-lg border border-border bg-card shadow-sm",
          className,
        )}
      >
        <div className="flex items-start gap-2 px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="truncate text-sm font-semibold text-foreground">{agent.agent_name}</span>
              {isApproved && (
                <BadgeCheck className="size-4 shrink-0 text-foreground" aria-label="Verified agent" />
              )}
            </div>
            {agent.company_name && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">{agent.company_name}</p>
            )}
            {agent.experience_years && (
              <p className="mt-0.5 text-xs text-muted-foreground">{agent.experience_years} yrs experience</p>
            )}
            {listingCount > 0 && (
              <Badge variant="secondary" className="mt-1.5 text-[10px] font-normal">
                Covers {listingCount} listing{listingCount === 1 ? "" : "s"}
              </Badge>
            )}
          </div>

          {canExpand && (
            <button
              type="button"
              onClick={() => setExpanded((p) => !p)}
              className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              aria-label={expanded ? "Collapse agent details" : "Expand agent details"}
            >
              {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </button>
          )}
        </div>

        {expanded && listingCount > 0 && (
          <ul className="list-disc space-y-0.5 px-3 pb-2 pl-6 text-xs text-muted-foreground">
            {propertyIds.map((pid) => (
              <li key={pid} className="leading-snug">
                {listingLabel(pid, propertyTitles)}
              </li>
            ))}
          </ul>
        )}

        {expanded && areas.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
            {areas.map((area) => (
              <Badge key={area} variant="secondary" className="text-xs font-normal">
                {area}
              </Badge>
            ))}
          </div>
        )}

        {primaryPropertyId != null && (
          <ContactCtaIconRow
            variant="agent"
            subjectLabel={subjectLabel}
            onCtaClick={openCta}
          />
        )}
      </div>

      {primaryPropertyId != null && (
        <PropertyContactSheet
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          channel={sheetChannel}
          context={sheetContext}
          preloadedContact={preloaded}
          sessionId={sessionId}
          uiSurface="agent_contacts_list"
          onSubmitLead={onSubmitLead}
        />
      )}
    </>
  );
}

function coverageSubtitle(coverage: AgentCoverage | undefined, agentCount: number): string {
  if (!coverage || coverage.requested_count <= 0) {
    return agentCount > 1 ? "Scroll for more agents" : "";
  }
  const { requested_count, resolved_count } = coverage;
  if (resolved_count >= requested_count) {
    return `covering ${resolved_count} listing${resolved_count === 1 ? "" : "s"}`;
  }
  return `covering ${resolved_count} of ${requested_count} listings`;
}

/* ─── Multi-agent container ───────────────────────────────────────────────── */

interface AgentContactsListProps {
  agents: AgentContact[];
  coverage?: AgentCoverage;
  propertyTitles?: Record<number, string>;
  note?: string;
  sessionId: string;
  searchSummary?: string;
  fallbackPropertyIds: number[];
  onSubmitLead: AgentContactCardProps["onSubmitLead"];
  onDismiss?: () => void;
  className?: string;
}

export function AgentContactsList({
  agents,
  coverage,
  propertyTitles,
  note,
  sessionId,
  searchSummary,
  fallbackPropertyIds,
  onSubmitLead,
  onDismiss,
  className,
}: AgentContactsListProps) {
  if (!agents || agents.length === 0) return null;

  const subtitle = coverageSubtitle(coverage, agents.length);
  const hasUnresolved = (coverage?.unresolved_property_ids?.length ?? 0) > 0;

  return (
    <div
      className={cn(
        "message-appear overflow-hidden rounded-lg border border-border bg-card shadow-sm border-l-[3px] border-l-primary",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2 px-4 pt-4 pb-2">
        <div>
          <p className="text-sm font-semibold text-foreground">
            Listing agents
            <span className="ml-1.5 font-normal text-muted-foreground">({agents.length})</span>
            {subtitle && (
              <span className="ml-1.5 font-normal text-muted-foreground">· {subtitle}</span>
            )}
          </p>
          {agents.length > 1 && !subtitle && (
            <p className="mt-0.5 text-[10px] text-muted-foreground">Scroll for more agents</p>
          )}
          {hasUnresolved && (
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {coverage!.unresolved_property_ids.length} listing
              {coverage!.unresolved_property_ids.length === 1 ? "" : "s"} could not be matched to a contact.
            </p>
          )}
          {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label="Dismiss"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      <div
        className={cn(
          "overflow-y-auto overscroll-contain scrollbar-thin px-4 pb-4",
          agents.length > 1 && "max-h-56",
        )}
        role={agents.length > 1 ? "region" : undefined}
        aria-label={agents.length > 1 ? "Listing agents, scrollable" : undefined}
      >
        <div className="flex flex-col gap-3 pr-1">
          {agents.map((agent) => (
            <AgentContactCard
              key={agent.agent_id}
              agent={agent}
              sessionId={sessionId}
              searchSummary={searchSummary}
              fallbackPropertyIds={fallbackPropertyIds}
              propertyTitles={propertyTitles}
              onSubmitLead={onSubmitLead}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
