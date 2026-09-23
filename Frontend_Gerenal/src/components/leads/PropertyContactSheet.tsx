/**
 * PropertyContactSheet — per-listing CTA flows (Call / WhatsApp / Email).
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Phone,
  MessageCircle,
  Mail,
  BadgeCheck,
  Loader2,
  ExternalLink,
  SendHorizonal,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { cn, buildPropqaWhatsAppMessage, buildPropqaWhatsAppUrl } from "@/lib/utils";
import { LeadCaptureForm, type LeadCaptureHitlPayload } from "./LeadCaptureForm";
import type { LeadSubmitData } from "./LeadActions";
import type { PropertyContact } from "@/hooks/usePropertyContact";
import { usePropertyContact } from "@/hooks/usePropertyContact";

export type CtaChannel = "phone" | "whatsapp" | "email";

export interface PropertyContactContext {
  propertyId: number;
  /** All property IDs for lead submit (e.g. agent's matched listings) */
  propertyIds?: number[];
  propertyTitle: string;
  price?: string | null;
  propqaUrl?: string | null;
}

interface PropertyContactSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channel: CtaChannel | null;
  context: PropertyContactContext | null;
  /** When set (Mode B agent list), skip API fetch and use this contact */
  preloadedContact?: PropertyContact | null;
  sessionId: string;
  /** Where the CTA was triggered (property sidebar vs agent list). */
  uiSurface?: string;
  onSubmitLead: (data: LeadSubmitData) => Promise<void>;
}

function resolveLeadPropertyIds(ctx: PropertyContactContext): number[] {
  if (ctx.propertyIds?.length) return ctx.propertyIds;
  return [ctx.propertyId];
}

const CHANNEL_META: Record<
  CtaChannel,
  { title: string; icon: ReactNode }
> = {
  phone: { title: "Call listing contact", icon: <Phone className="size-4" /> },
  whatsapp: { title: "WhatsApp", icon: <MessageCircle className="size-4" /> },
  email: { title: "Email", icon: <Mail className="size-4" /> },
};

function maskPhone(num: string): string {
  const digits = num.replace(/\D/g, "");
  if (digits.length < 4) return num;
  return `•••• ${digits.slice(-4)}`;
}

export function PropertyContactSheet({
  open,
  onOpenChange,
  channel,
  context,
  preloadedContact = null,
  sessionId,
  uiSurface = "property_card_sidebar",
  onSubmitLead,
}: PropertyContactSheetProps) {
  const { fetchContact, recordCtaClick, loading, error, clearError } = usePropertyContact();
  const [contact, setContact] = useState<PropertyContact | null>(null);
  const [fetching, setFetching] = useState(false);
  const [step, setStep] = useState<"main" | "done">("main");

  const usePreloaded = Boolean(preloadedContact);
  const waMessage = useMemo(
    () => buildPropqaWhatsAppMessage(context?.propqaUrl),
    [context?.propqaUrl],
  );
  const canUseWhatsApp = Boolean(context?.propqaUrl);

  useEffect(() => {
    if (!open || !context?.propertyId) {
      setContact(null);
      setStep("main");
      clearError();
      return;
    }
    if (preloadedContact) {
      setContact(preloadedContact);
      setFetching(false);
      return;
    }
    setFetching(true);
    void fetchContact(context.propertyId).then((c) => {
      setContact(c);
      setFetching(false);
    });
  }, [
    open,
    context?.propertyId,
    context?.propertyTitle,
    context?.price,
    context?.propqaUrl,
    preloadedContact,
    fetchContact,
    clearError,
  ]);

  const isLoading = !usePreloaded && fetching;

  function handleClose(next: boolean) {
    if (!next) {
      setStep("main");
    }
    onOpenChange(next);
  }

  const phoneNum = contact?.mobile || contact?.phone;
  const isApproved = contact?.verification_status === "approved";

  async function handleCallNow() {
    if (!phoneNum || !context) return;
    await recordCtaClick(context.propertyId, "phone", sessionId, { ui_surface: uiSurface });
    window.open(`tel:${phoneNum}`, "_self");
    setStep("done");
  }

  async function handleWhatsAppOpen() {
    if (!context?.propqaUrl) return;
    await recordCtaClick(context.propertyId, "whatsapp", sessionId, { ui_surface: uiSurface });
    window.open(buildPropqaWhatsAppUrl(waMessage), "_blank", "noopener,noreferrer");
    setStep("done");
  }

  const capturePayload: LeadCaptureHitlPayload = {
    interrupt_id: "property-card-lead-capture",
    mode: "A",
    prompt: "Send your details to the listing contact",
    fields: [
      { name: "buyer_name", label: "Your Name", type: "text", required: true },
      { name: "buyer_email", label: "Email Address", type: "email", required: true },
      { name: "buyer_phone", label: "Phone / WhatsApp", type: "tel", required: true },
    ],
    context_summary: {
      search_summary: context?.propertyTitle,
      matched_property_ids: context ? resolveLeadPropertyIds(context) : [],
    },
  };

  if (!channel || !context) return null;

  const meta = CHANNEL_META[channel];
  const useWideLayout = channel === "email" && step === "main";

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={cn(
          "max-h-[90vh] overflow-y-auto p-4 sm:p-6",
          useWideLayout
            ? "!max-w-4xl !w-[min(56rem,calc(100vw-2rem))]"
            : "!max-w-md !w-[min(28rem,calc(100vw-2rem))]",
        )}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            {meta.icon}
            {meta.title}
          </DialogTitle>
          <DialogDescription className="line-clamp-2 text-left">
            {context.propertyTitle}
            {context.price ? ` · ${context.price}` : ""}
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading contact…
          </div>
        )}

        {!isLoading && error && (
          <div className="flex flex-col gap-3 py-4">
            <p className="text-sm text-muted-foreground">{error}</p>
            {context.propqaUrl && (
              <a
                href={context.propqaUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-1.5 rounded-md border py-2 text-xs font-semibold hover:bg-accent"
              >
                View on PropQA
                <ExternalLink className="size-3.5" />
              </a>
            )}
          </div>
        )}

        {!isLoading && !error && contact && step === "done" && (
          <div className="flex items-start gap-3 rounded-lg border border-l-[3px] border-l-primary bg-card p-3">
            <SendHorizonal className="size-5 shrink-0 text-primary" />
            <div>
              <p className="text-sm font-medium">Done</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Your action was recorded. The listing contact may follow up if you sent an inquiry.
              </p>
            </div>
          </div>
        )}

        {!isLoading && !error && step !== "done" && (contact || (channel === "whatsapp" && canUseWhatsApp)) && (
          <>
            {contact && (
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-semibold">{contact.agent_name}</span>
                {isApproved && (
                  <BadgeCheck className="size-4 text-foreground" aria-label="Verified" />
                )}
                <Badge variant="secondary" className="text-[10px]">
                  {contact.contact_source === "agency" ? "Agency" : "Listing agent"}
                </Badge>
              </div>
              {contact.company_name && (
                <p className="mt-0.5 text-xs text-muted-foreground">{contact.company_name}</p>
              )}
            </div>
            )}

            {contact && channel === "phone" && step === "main" && (
              <div className="flex flex-col gap-3">
                {phoneNum ? (
                  <p className="text-sm text-muted-foreground">
                    Phone: <span className="font-medium text-foreground">{maskPhone(phoneNum)}</span>
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">No phone number on file.</p>
                )}
                <DialogFooter className="flex-col gap-2 sm:flex-col">
                  <Button
                    className="w-full gap-2"
                    disabled={!phoneNum}
                    onClick={() => void handleCallNow()}
                  >
                    <Phone className="size-4" />
                    Call now
                  </Button>
                </DialogFooter>
              </div>
            )}

            {channel === "whatsapp" && step === "main" && (
              <div className="flex flex-col gap-3">
                <p className="text-xs text-muted-foreground">
                  Your message will be sent to PropQA on WhatsApp. PropQA will forward your inquiry to
                  the listing agent.
                </p>
                <div>
                  <Label htmlFor="wa-message" className="text-xs">
                    Message preview
                  </Label>
                  <textarea
                    id="wa-message"
                    readOnly
                    className={cn(
                      "mt-1 flex min-h-[100px] w-full rounded-md border border-input bg-muted/40 px-3 py-2 text-sm",
                      "cursor-default ring-offset-background focus-visible:outline-none",
                    )}
                    value={waMessage}
                  />
                </div>
                <DialogFooter>
                  <Button
                    className="w-full gap-2"
                    disabled={!canUseWhatsApp}
                    onClick={() => void handleWhatsAppOpen()}
                  >
                    <MessageCircle className="size-4" />
                    Continue in WhatsApp
                  </Button>
                </DialogFooter>
              </div>
            )}

            {contact && channel === "email" && step === "main" && (
              <LeadCaptureForm
                variant="sheet"
                payload={capturePayload}
                agentEmail={contact?.email}
                agentName={contact?.agent_name}
                sessionId={sessionId}
                listingContext={context}
                onSubmit={async (data) => {
                  await recordCtaClick(context.propertyId, "email", sessionId, {
                    ui_surface: uiSurface,
                  });
                  await onSubmitLead({
                    ...data,
                    property_ids: resolveLeadPropertyIds(context),
                    ui_surface: uiSurface ?? "property_contact_email_form",
                  });
                  setStep("done");
                }}
                onDismiss={() => handleClose(false)}
              />
            )}
          </>
        )}

        {context.propqaUrl && !isLoading && (
          <a
            href={context.propqaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center justify-center gap-1 text-xs text-primary hover:underline"
          >
            View full listing on PropQA
            <ExternalLink className="size-3" />
          </a>
        )}
      </DialogContent>
    </Dialog>
  );
}
