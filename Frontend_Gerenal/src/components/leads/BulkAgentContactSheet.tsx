/**
 * BulkAgentContactSheet — contact up to 5 listing agents in one flow.
 * Buyer details entered once; per-listing agent email previews and To fields.
 */

import { useEffect, useMemo, useState } from "react";
import {
  UserRound,
  Mail,
  Phone,
  SendHorizonal,
  Loader2,
  ArrowDownToLine,
  ArrowUpFromLine,
  BadgeCheck,
  X,
  Plus,
} from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn, resolvePropqaUrl } from "@/lib/utils";
import {
  buildInquiryEmailBody,
  buildInquiryEmailHtml,
  DEFAULT_PROPQA_LEADS_FROM_EMAIL,
} from "@/lib/leadInquiryEmail";
import { pickCardTitle, pickPriceLine } from "@/lib/propertyCard";
import { parsePropertyId } from "@/lib/propertyIds";
import { MAX_INQUIRY_PROPERTY_IDS } from "@/lib/followUpSuggestions";
import { LeadInquiryEmailPreview } from "./LeadInquiryEmailPreview";
import type { LeadSubmitData } from "./LeadActions";
import type { PropertyContact } from "@/hooks/usePropertyContact";
import { usePropertyContact } from "@/hooks/usePropertyContact";
import type { PropertyCard } from "@/store/chatStore";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface ListingEntry {
  propertyId: number;
  title: string;
  price: string | null;
  propqaUrl: string | null;
  contact: PropertyContact | null;
  loading: boolean;
  toEmail: string;
}

interface BulkAgentContactSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedPropertyIds: number[];
  onSelectedPropertyIdsChange: (ids: number[]) => void;
  cards: PropertyCard[];
  sessionId: string;
  searchSummary?: string;
  onSubmitLead: (data: LeadSubmitData) => Promise<void>;
}

function cardContext(card: PropertyCard | undefined, propertyId: number) {
  const rawPath =
    (card?.url as string | undefined) ||
    (card?.link as string | undefined) ||
    (card?.slug ? `/property/${String(card.slug)}` : null);
  return {
    title: card ? pickCardTitle(card) : `Property #${propertyId}`,
    price: card ? pickPriceLine(card) : null,
    propqaUrl: resolvePropqaUrl(rawPath),
  };
}

export function BulkAgentContactSheet({
  open,
  onOpenChange,
  selectedPropertyIds,
  onSelectedPropertyIdsChange,
  cards,
  sessionId,
  searchSummary,
  onSubmitLead,
}: BulkAgentContactSheetProps) {
  const { fetchContact } = usePropertyContact();
  const [buyerName, setBuyerName] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("");
  const [buyerPhone, setBuyerPhone] = useState("");
  const [fromEmail, setFromEmail] = useState(DEFAULT_PROPQA_LEADS_FROM_EMAIL);
  const [manualId, setManualId] = useState("");
  const [listings, setListings] = useState<ListingEntry[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const cardById = useMemo(() => {
    const map = new Map<number, PropertyCard>();
    for (const card of cards) {
      const id = parsePropertyId(card);
      if (id != null) map.set(id, card);
    }
    return map;
  }, [cards]);

  useEffect(() => {
    if (!open) {
      setErrors({});
      setDone(false);
      setManualId("");
      return;
    }

    setListings(
      selectedPropertyIds.map((propertyId) => {
        const ctx = cardContext(cardById.get(propertyId), propertyId);
        return {
          propertyId,
          title: ctx.title,
          price: ctx.price,
          propqaUrl: ctx.propqaUrl,
          contact: null,
          loading: true,
          toEmail: "",
        };
      }),
    );

    let cancelled = false;
    for (const propertyId of selectedPropertyIds) {
      void fetchContact(propertyId).then((contact) => {
        if (cancelled) return;
        setListings((prev) =>
          prev.map((row) =>
            row.propertyId === propertyId
              ? {
                  ...row,
                  contact,
                  loading: false,
                  toEmail: contact?.email?.trim() ?? row.toEmail,
                }
              : row,
          ),
        );
      });
    }

    return () => {
      cancelled = true;
    };
  }, [open, selectedPropertyIds, cardById, fetchContact]);

  function removePropertyId(id: number) {
    onSelectedPropertyIdsChange(selectedPropertyIds.filter((x) => x !== id));
  }

  function addManualPropertyId() {
    const parsed = Number.parseInt(manualId.trim(), 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      toast.error("Enter a valid property ID");
      return;
    }
    if (selectedPropertyIds.includes(parsed)) {
      toast.message("That property is already selected");
      return;
    }
    if (selectedPropertyIds.length >= MAX_INQUIRY_PROPERTY_IDS) {
      toast.message(`You can add up to ${MAX_INQUIRY_PROPERTY_IDS} listings`);
      return;
    }
    onSelectedPropertyIdsChange([...selectedPropertyIds, parsed]);
    setManualId("");
  }

  function updateToEmail(propertyId: number, toEmail: string) {
    setListings((prev) =>
      prev.map((row) => (row.propertyId === propertyId ? { ...row, toEmail } : row)),
    );
  }

  function validate(): boolean {
    const next: Record<string, string> = {};
    if (!buyerName.trim()) next.buyer_name = "Your name is required";
    if (!buyerEmail.trim()) next.buyer_email = "Email address is required";
    else if (!EMAIL_RE.test(buyerEmail.trim())) next.buyer_email = "Please enter a valid email address";
    if (!buyerPhone.trim()) next.buyer_phone = "Phone / WhatsApp is required";
    else if (!/^[\d\s+\-()]{6,20}$/.test(buyerPhone.trim())) {
      next.buyer_phone = "Please enter a valid phone number";
    }
    if (!fromEmail.trim()) next.from_email = "PropQA email (From) is required";
    else if (!EMAIL_RE.test(fromEmail.trim())) next.from_email = "Please enter a valid email address";
    if (selectedPropertyIds.length === 0) {
      next._listings = `Add at least one listing from the sidebar (max ${MAX_INQUIRY_PROPERTY_IDS}).`;
    }
    for (const row of listings) {
      if (!row.toEmail.trim()) next[`to_${row.propertyId}`] = "Agent email is required";
      else if (!EMAIL_RE.test(row.toEmail.trim())) {
        next[`to_${row.propertyId}`] = "Please enter a valid email address";
      }
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate() || submitting) return;
    setSubmitting(true);
    try {
      for (const row of listings) {
        const emailInput = {
          buyerName: buyerName.trim(),
          buyerEmail: buyerEmail.trim(),
          buyerPhone: buyerPhone.trim(),
          propertyTitle: row.title,
          propertyId: row.propertyId,
          price: row.price,
          propqaUrl: row.propqaUrl,
          agentName: row.contact?.agent_name ?? null,
          sessionId,
        };
        await onSubmitLead({
          buyer_name: buyerName.trim(),
          buyer_email: buyerEmail.trim(),
          buyer_phone: buyerPhone.trim(),
          property_ids: [row.propertyId],
          from_email: fromEmail.trim(),
          to_email: row.toEmail.trim(),
          message_override: buildInquiryEmailBody(emailInput),
          message_html_override: buildInquiryEmailHtml(emailInput),
          ui_surface: "bulk_agent_contact",
        });
      }
      setDone(true);
      onSelectedPropertyIdsChange([]);
      toast.success(
        listings.length === 1
          ? "Inquiry sent to the listing agent."
          : `Inquiries sent to ${listings.length} listing agents.`,
      );
    } catch {
      setErrors({ _form: "Submission failed. Please try again." });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Contact with Agents</DialogTitle>
          <DialogDescription>
            {searchSummary
              ? `Send your details to listing agents for: ${searchSummary}`
              : `Pick up to ${MAX_INQUIRY_PROPERTY_IDS} listings from the sidebar, then send one inquiry per agent via PropQA.`}
          </DialogDescription>
        </DialogHeader>

        {done ? (
          <div className="message-appear flex items-start gap-3 rounded-lg border border-border bg-card p-4 shadow-sm border-l-[3px] border-l-primary">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <SendHorizonal className="size-4" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Inquiries sent!</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                The listing agent(s) will reach out within 24 hours.
              </p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="mt-3"
                onClick={() => onOpenChange(false)}
              >
                Close
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-5">
            <section className="flex flex-col gap-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Selected listings ({selectedPropertyIds.length}/{MAX_INQUIRY_PROPERTY_IDS})
              </p>
              <div className="flex flex-wrap gap-2">
                {selectedPropertyIds.length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    Use &quot;Add to inquiry&quot; on sidebar cards, or enter an ID below.
                  </p>
                ) : (
                  selectedPropertyIds.map((id) => (
                    <Badge key={id} variant="secondary" className="gap-1 pr-1">
                      #{id}
                      <button
                        type="button"
                        className="rounded-sm p-0.5 hover:bg-muted"
                        aria-label={`Remove property ${id}`}
                        onClick={() => removePropertyId(id)}
                      >
                        <X className="size-3" />
                      </button>
                    </Badge>
                  ))
                )}
              </div>
              <div className="flex gap-2">
                <Input
                  value={manualId}
                  onChange={(e) => setManualId(e.target.value)}
                  placeholder="Property ID"
                  className="h-8 max-w-[140px] text-sm"
                  inputMode="numeric"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 gap-1"
                  disabled={selectedPropertyIds.length >= MAX_INQUIRY_PROPERTY_IDS}
                  onClick={addManualPropertyId}
                >
                  <Plus className="size-3.5" /> Add ID
                </Button>
              </div>
              {errors._listings && (
                <p className="text-xs text-destructive">{errors._listings}</p>
              )}
            </section>

            <section className="flex flex-col gap-3 border-t border-border/60 pt-4">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Your details
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1 sm:col-span-2">
                  <Label htmlFor="bulk-buyer-name" className="text-xs font-medium">
                    Your Name<span className="ml-0.5 text-destructive">*</span>
                  </Label>
                  <div className="relative">
                    <UserRound className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="bulk-buyer-name"
                      value={buyerName}
                      onChange={(e) => setBuyerName(e.target.value)}
                      className={cn("h-9 pl-9 text-sm", errors.buyer_name && "border-destructive")}
                      autoComplete="name"
                    />
                  </div>
                  {errors.buyer_name && (
                    <p className="text-xs text-destructive">{errors.buyer_name}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="bulk-buyer-email" className="text-xs font-medium">
                    Email Address<span className="ml-0.5 text-destructive">*</span>
                  </Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="bulk-buyer-email"
                      type="email"
                      value={buyerEmail}
                      onChange={(e) => setBuyerEmail(e.target.value)}
                      className={cn("h-9 pl-9 text-sm", errors.buyer_email && "border-destructive")}
                      autoComplete="email"
                    />
                  </div>
                  {errors.buyer_email && (
                    <p className="text-xs text-destructive">{errors.buyer_email}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="bulk-buyer-phone" className="text-xs font-medium">
                    Phone / WhatsApp<span className="ml-0.5 text-destructive">*</span>
                  </Label>
                  <div className="relative">
                    <Phone className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="bulk-buyer-phone"
                      type="tel"
                      value={buyerPhone}
                      onChange={(e) => setBuyerPhone(e.target.value)}
                      className={cn("h-9 pl-9 text-sm", errors.buyer_phone && "border-destructive")}
                      autoComplete="tel"
                    />
                  </div>
                  {errors.buyer_phone && (
                    <p className="text-xs text-destructive">{errors.buyer_phone}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1 sm:col-span-2">
                  <Label htmlFor="bulk-from-email" className="flex items-center gap-1 text-xs font-medium">
                    <ArrowUpFromLine className="size-3 text-muted-foreground" />
                    PropQA Email (From)<span className="ml-0.5 text-destructive">*</span>
                  </Label>
                  <Input
                    id="bulk-from-email"
                    type="email"
                    value={fromEmail}
                    onChange={(e) => setFromEmail(e.target.value)}
                    className={cn("h-9 text-sm", errors.from_email && "border-destructive")}
                  />
                  {errors.from_email && (
                    <p className="text-xs text-destructive">{errors.from_email}</p>
                  )}
                </div>
              </div>
            </section>

            {listings.length > 0 && (
              <section className="flex flex-col gap-4 border-t border-border/60 pt-4">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Agent contacts & email preview
                </p>
                {listings.map((row) => {
                  const emailInput = {
                    buyerName: buyerName.trim(),
                    buyerEmail: buyerEmail.trim(),
                    buyerPhone: buyerPhone.trim(),
                    propertyTitle: row.title,
                    propertyId: row.propertyId,
                    price: row.price,
                    propqaUrl: row.propqaUrl,
                    agentName: row.contact?.agent_name ?? null,
                    sessionId,
                  };
                  const emailHtml = buildInquiryEmailHtml(emailInput);
                  const agentName = row.contact?.agent_name?.trim() || "Listing agent";
                  const company = row.contact?.company_name?.trim();
                  return (
                    <div
                      key={row.propertyId}
                      className="rounded-lg border border-border/80 bg-muted/20 p-3"
                    >
                      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">{row.title}</p>
                          <p className="text-xs text-muted-foreground">
                            #{row.propertyId}
                            {row.price ? ` · ${row.price}` : ""}
                          </p>
                        </div>
                        {row.loading ? (
                          <Loader2 className="size-4 animate-spin text-muted-foreground" />
                        ) : (
                          <div className="text-right text-xs">
                            <p className="flex items-center justify-end gap-1 font-medium text-foreground">
                              {agentName}
                              {row.contact?.verification_status === "approved" && (
                                <BadgeCheck className="size-3.5 text-primary" />
                              )}
                            </p>
                            {company && (
                              <p className="text-muted-foreground">{company}</p>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex flex-col gap-2">
                        <Label
                          htmlFor={`bulk-to-${row.propertyId}`}
                          className="flex items-center gap-1 text-xs font-medium"
                        >
                          <ArrowDownToLine className="size-3 text-muted-foreground" />
                          Agent Email (To)<span className="ml-0.5 text-destructive">*</span>
                        </Label>
                        <Input
                          id={`bulk-to-${row.propertyId}`}
                          type="email"
                          value={row.toEmail}
                          onChange={(e) => updateToEmail(row.propertyId, e.target.value)}
                          className={cn(
                            "h-9 text-sm",
                            errors[`to_${row.propertyId}`] && "border-destructive",
                          )}
                          disabled={row.loading}
                        />
                        {errors[`to_${row.propertyId}`] && (
                          <p className="text-xs text-destructive">
                            {errors[`to_${row.propertyId}`]}
                          </p>
                        )}
                        <LeadInquiryEmailPreview html={emailHtml} />
                      </div>
                    </div>
                  );
                })}
              </section>
            )}

            <div className="flex flex-col gap-2 border-t border-border/60 pt-4">
              {errors._form && (
                <p className="text-center text-xs text-destructive">{errors._form}</p>
              )}
              <Button
                type="submit"
                size="sm"
                className="w-full gap-2 sm:max-w-xs"
                disabled={submitting || selectedPropertyIds.length === 0}
              >
                {submitting ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" /> Sending…
                  </>
                ) : (
                  <>
                    <SendHorizonal className="size-3.5" /> Send inquiry via PropQA
                  </>
                )}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
