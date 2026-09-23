/**
 * Branded HTML preview of the lead inquiry email (Template #13).
 */

import { cn } from "@/lib/utils";

interface LeadInquiryEmailPreviewProps {
  html: string;
  className?: string;
}

export function LeadInquiryEmailPreview({ html, className }: LeadInquiryEmailPreviewProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div
        id="lie-email-body"
        className={cn(
          "max-h-[280px] overflow-y-auto rounded-md border border-input bg-[#f3f6fb] p-2",
          "text-[11px] leading-relaxed",
        )}
        aria-label="Body of email preview"
      >
        <div
          className="origin-top-left scale-[0.92] transform"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Preview of the email sent to the listing agent. Updates automatically from your details and listing context.
      </p>
    </div>
  );
}
