/**
 * LeadInquiryEmailForm — email-compose style inquiry for "Send inquiry via PropQA".
 * Buyer fields and From/To are editable; body is a read-only preview.
 */

import { useEffect, useMemo, useState } from "react";
import {
  UserRound,
  Mail,
  Phone,
  SendHorizonal,
  X,
  Loader2,
  ArrowDownToLine,
  ArrowUpFromLine,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  buildInquiryEmailBody,
  buildInquiryEmailHtml,
  DEFAULT_PROPQA_LEADS_FROM_EMAIL,
} from "@/lib/leadInquiryEmail";
import type { PropertyContactContext } from "./PropertyContactSheet";
import { LeadInquiryEmailPreview } from "./LeadInquiryEmailPreview";

export interface LeadInquiryEmailSubmitData {
  buyer_name: string;
  buyer_email: string;
  buyer_phone: string;
  property_ids: number[];
  from_email: string;
  to_email: string;
  message_override: string;
  message_html_override: string;
}

interface LeadInquiryEmailFormProps {
  context: PropertyContactContext;
  propertyIds: number[];
  agentEmail?: string | null;
  agentName?: string | null;
  sessionId?: string;
  prompt?: string;
  contextLabel?: "listing" | "search";
  variant?: "default" | "sheet";
  submitLabel?: string;
  onSubmit: (data: LeadInquiryEmailSubmitData) => Promise<void> | void;
  onDismiss?: () => void;
  className?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function LeadInquiryEmailForm({
  context,
  propertyIds,
  agentEmail,
  agentName,
  sessionId,
  prompt = "Send your details to the listing contact",
  contextLabel = "listing",
  variant = "default",
  submitLabel = "Connect me with an agent",
  onSubmit,
  onDismiss,
  className,
}: LeadInquiryEmailFormProps) {
  const embedded = variant === "sheet";
  const [buyerName, setBuyerName] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("");
  const [buyerPhone, setBuyerPhone] = useState("");
  const [fromEmail, setFromEmail] = useState(DEFAULT_PROPQA_LEADS_FROM_EMAIL);
  const [toEmail, setToEmail] = useState(agentEmail?.trim() ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const next = agentEmail?.trim();
    if (next) {
      setToEmail((prev) => (prev.trim() ? prev : next));
    }
  }, [agentEmail]);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const emailInput = useMemo(
    () => ({
      buyerName,
      buyerEmail,
      buyerPhone,
      propertyTitle: context.propertyTitle,
      propertyId: context.propertyId ?? propertyIds[0] ?? null,
      price: context.price,
      propqaUrl: context.propqaUrl,
      agentName,
      sessionId,
    }),
    [
      buyerName,
      buyerEmail,
      buyerPhone,
      context.propertyTitle,
      context.propertyId,
      context.price,
      context.propqaUrl,
      agentName,
      sessionId,
      propertyIds,
    ],
  );

  const emailBody = useMemo(() => buildInquiryEmailBody(emailInput), [emailInput]);
  const emailHtml = useMemo(() => buildInquiryEmailHtml(emailInput), [emailInput]);

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
    if (!toEmail.trim()) next.to_email = "Agent email (To) is required";
    else if (!EMAIL_RE.test(toEmail.trim())) next.to_email = "Please enter a valid email address";
    if (propertyIds.length === 0) {
      next._form = "No listing is linked to this inquiry. Try again from a property card.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate() || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit({
        buyer_name: buyerName.trim(),
        buyer_email: buyerEmail.trim(),
        buyer_phone: buyerPhone.trim(),
        property_ids: propertyIds,
        from_email: fromEmail.trim(),
        to_email: toEmail.trim(),
        message_override: emailBody,
        message_html_override: emailHtml,
      });
      setSubmitted(true);
    } catch {
      setErrors({ _form: "Submission failed. Please try again." });
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div
        className={cn(
          "message-appear flex items-start gap-3 rounded-lg border border-border bg-card p-4 shadow-sm border-l-[3px] border-l-primary",
          className,
        )}
      >
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <SendHorizonal className="size-4" />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">Inquiry sent!</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Your message will be routed to the listing agent via PropQA.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "message-appear w-full min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-sm border-l-[3px] border-l-primary",
        embedded && "rounded-none border-0 border-l-0 bg-transparent shadow-none",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-start justify-between gap-2 border-b border-border/60 pb-3",
          embedded ? "px-0 pt-0" : "px-4 pt-4",
        )}
      >
        <div>
          <p className="text-sm font-semibold text-foreground">{prompt}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {contextLabel === "search" ? "Searching for: " : "Listing: "}
            <span className="font-medium text-foreground">{context.propertyTitle}</span>
            {context.price ? (
              <span className="text-muted-foreground"> · {context.price}</span>
            ) : null}
          </p>
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

      <form
        onSubmit={(e) => void handleSubmit(e)}
        className={cn(
          "flex w-full min-w-0 flex-col gap-5",
          embedded ? "px-0 pb-0 pt-4" : "px-4 pb-4 pt-3",
        )}
      >
        <div className="grid w-full min-w-0 gap-6 lg:grid-cols-2 lg:gap-8 lg:items-start">
          <section className="flex min-w-0 flex-col gap-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Your details
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-1 sm:col-span-2">
          <Label htmlFor="lie-buyer-name" className="text-xs font-medium">
            Your Name<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <div className="relative">
            <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
              <UserRound className="size-4 text-muted-foreground" />
            </div>
            <Input
              id="lie-buyer-name"
              value={buyerName}
              onChange={(e) => {
                setBuyerName(e.target.value);
                if (errors.buyer_name) setErrors((p) => ({ ...p, buyer_name: "" }));
              }}
              className={cn("h-9 pl-9 text-sm", errors.buyer_name && "border-destructive")}
              disabled={submitting}
              autoComplete="name"
            />
          </div>
          {errors.buyer_name && <p className="text-xs text-destructive">{errors.buyer_name}</p>}
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="lie-buyer-email" className="text-xs font-medium">
            Email Address<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <div className="relative">
            <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
              <Mail className="size-4 text-muted-foreground" />
            </div>
            <Input
              id="lie-buyer-email"
              type="email"
              value={buyerEmail}
              onChange={(e) => {
                setBuyerEmail(e.target.value);
                if (errors.buyer_email) setErrors((p) => ({ ...p, buyer_email: "" }));
              }}
              className={cn("h-9 pl-9 text-sm", errors.buyer_email && "border-destructive")}
              disabled={submitting}
              autoComplete="email"
            />
          </div>
          {errors.buyer_email && <p className="text-xs text-destructive">{errors.buyer_email}</p>}
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="lie-buyer-phone" className="text-xs font-medium">
            Phone / WhatsApp<span className="ml-0.5 text-destructive">*</span>
          </Label>
          <div className="relative">
            <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
              <Phone className="size-4 text-muted-foreground" />
            </div>
            <Input
              id="lie-buyer-phone"
              type="tel"
              value={buyerPhone}
              onChange={(e) => {
                setBuyerPhone(e.target.value);
                if (errors.buyer_phone) setErrors((p) => ({ ...p, buyer_phone: "" }));
              }}
              className={cn("h-9 pl-9 text-sm", errors.buyer_phone && "border-destructive")}
              disabled={submitting}
              autoComplete="tel"
            />
          </div>
          {errors.buyer_phone && <p className="text-xs text-destructive">{errors.buyer_phone}</p>}
        </div>
            </div>
          </section>

          <section className="flex min-w-0 flex-col gap-3 lg:border-l lg:border-border/60 lg:pl-8">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Email preview
            </p>
            <div className="grid gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="lie-from-email" className="flex items-center gap-1 text-xs font-medium">
                <ArrowUpFromLine className="size-3 text-muted-foreground" />
                PropQA Email (From)<span className="ml-0.5 text-destructive">*</span>
              </Label>
              <Input
                id="lie-from-email"
                type="email"
                value={fromEmail}
                onChange={(e) => {
                  setFromEmail(e.target.value);
                  if (errors.from_email) setErrors((p) => ({ ...p, from_email: "" }));
                }}
                className={cn("h-9 text-sm", errors.from_email && "border-destructive")}
                disabled={submitting}
              />
              {errors.from_email && (
                <p className="text-xs text-destructive">{errors.from_email}</p>
              )}
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="lie-to-email" className="flex items-center gap-1 text-xs font-medium">
                <ArrowDownToLine className="size-3 text-muted-foreground" />
                Agent Email (To)<span className="ml-0.5 text-destructive">*</span>
              </Label>
              <Input
                id="lie-to-email"
                type="email"
                value={toEmail}
                onChange={(e) => {
                  setToEmail(e.target.value);
                  if (errors.to_email) setErrors((p) => ({ ...p, to_email: "" }));
                }}
                placeholder={agentEmail ?? "agent@example.com"}
                className={cn("h-9 text-sm", errors.to_email && "border-destructive")}
                disabled={submitting}
              />
              {errors.to_email && <p className="text-xs text-destructive">{errors.to_email}</p>}
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="lie-email-body" className="text-xs font-medium text-foreground">
                Body of email
              </Label>
              <LeadInquiryEmailPreview html={emailHtml} />
            </div>
            </div>
          </section>
        </div>

        <div className="flex w-full min-w-0 flex-col gap-2 border-t border-border/60 pt-4">
          {errors._form && (
            <p className="text-center text-xs text-destructive">{errors._form}</p>
          )}

          <Button type="submit" size="sm" className="w-full gap-2 sm:max-w-xs" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" /> Sending…
              </>
            ) : (
              <>
                <SendHorizonal className="size-3.5" /> {submitLabel}
              </>
            )}
          </Button>

          <p className="max-w-prose text-[10px] leading-relaxed text-muted-foreground">
            Your details are only shared with the listing agent and never sold to third parties.
          </p>
        </div>
      </form>
    </div>
  );
}
