/** Default outbound address shown in PropQA email inquiry compose UI (matches Backend MAIL_FROM_ADDRESS). */
export const DEFAULT_PROPQA_LEADS_FROM_EMAIL = "support@propqa.ai";

const LEAD_SOURCE = "PropQA AI Chatbot";

export interface InquiryEmailBodyInput {
  buyerName: string;
  buyerEmail: string;
  buyerPhone: string;
  propertyTitle: string;
  propertyId?: number | null;
  price?: string | null;
  propqaUrl?: string | null;
  agentName?: string | null;
  sessionId?: string;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function listingRef(propertyId?: number | null): string {
  return propertyId ? `#${propertyId}` : "—";
}

function receivedAtLabel(): string {
  return new Date().toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

/** Plain-text fallback aligned with Template #13 copy. */
export function buildInquiryEmailBody(input: InquiryEmailBodyInput): string {
  const agentName = input.agentName?.trim() || "there";
  const buyerName = input.buyerName.trim() || "—";
  const buyerEmail = input.buyerEmail.trim() || "—";
  const buyerPhone = input.buyerPhone.trim() || "—";
  const ref = listingRef(input.propertyId);
  const when = receivedAtLabel();

  const lines = [
    `Hi ${agentName},`,
    "",
    `You've just received a new lead for ${input.propertyTitle}.`,
    "",
    "── Lead details ──────────────────────────────────",
    `  Prospect name:  ${buyerName}`,
    `  Source:         ${LEAD_SOURCE}`,
    `  Phone:          ${buyerPhone}`,
    `  Email:          ${buyerEmail}`,
    `  Listing ref:    ${ref}`,
    `  Received at:    ${when}`,
    "",
    "Fast follow-up increases conversion. We recommend reviewing this lead",
    "and contacting the prospect as soon as possible.",
  ];

  if (input.propqaUrl?.trim()) {
    lines.push("", `Open lead details: ${input.propqaUrl.trim()}`);
  }

  lines.push(
    "",
    "──────────────────────────────────────────────────",
    "PROPQA notifies assigned users as soon as lead ownership is established.",
  );

  return lines.join("\n");
}

/** Branded HTML preview matching approval pack Template #13. */
export function buildInquiryEmailHtml(input: InquiryEmailBodyInput): string {
  const agentName = escapeHtml(input.agentName?.trim() || "there");
  const title = escapeHtml(input.propertyTitle.trim() || "Property inquiry");
  const ref = escapeHtml(listingRef(input.propertyId));
  const buyerName = escapeHtml(input.buyerName.trim() || "—");
  const buyerEmail = escapeHtml(input.buyerEmail.trim() || "—");
  const buyerPhone = escapeHtml(input.buyerPhone.trim() || "—");
  const when = escapeHtml(receivedAtLabel());

  const ctaBlock = input.propqaUrl?.trim()
    ? `<div style="margin:24px 0 20px;">
          <a href="${escapeHtml(input.propqaUrl.trim())}" style="display:inline-block;text-decoration:none;background:#F54B4B;color:#fff;font-weight:700;font-size:14px;padding:14px 20px;border-radius:12px;box-shadow:0 12px 24px rgba(245,75,75,0.2);">Open lead details</a>
        </div>`
    : "";

  return `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f6fb;">
  <div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #dbe4ef;border-radius:24px;overflow:hidden;box-shadow:0 18px 40px rgba(14,34,57,0.1);">
    <div style="background:linear-gradient(135deg,#0E2239 0%,#153253 100%);padding:18px 22px;color:#fff;display:flex;justify-content:space-between;align-items:center;">
      <div style="font-weight:800;letter-spacing:0.08em;font-size:16px;">PROPQA</div>
      <div style="font-size:11px;text-transform:uppercase;padding:7px 10px;border-radius:999px;background:rgba(255,255,255,0.1);color:rgba(255,255,255,0.88);border:1px solid rgba(255,255,255,0.16);">Lead alert</div>
    </div>
    <div style="padding:28px 28px 18px;background:linear-gradient(180deg,#fff5f5 0%,#ffffff 100%);border-bottom:1px solid #f1f5f9;">
      <div style="display:inline-block;margin-bottom:12px;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#F54B4B;font-weight:800;background:rgba(245,75,75,0.08);border:1px solid rgba(245,75,75,0.14);border-radius:999px;padding:7px 10px;">New enquiry</div>
      <h1 style="margin:0 0 12px;font-size:28px;line-height:1.14;letter-spacing:-0.03em;color:#111827;">A new lead is waiting for your follow-up</h1>
      <p style="margin:0;font-size:16px;line-height:1.7;color:#475467;">Hi ${agentName}, you've just received a new lead for <strong>${title}</strong>.</p>
    </div>
    <div style="padding:24px 28px 30px;">
      <div style="background:#f8fafc;border:1px solid #e5edf6;border-radius:16px;padding:16px 18px;margin:16px 0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 16px;">
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Prospect name</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${buyerName}</div></div>
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Source</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${LEAD_SOURCE}</div></div>
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Phone</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${buyerPhone}</div></div>
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Email</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${buyerEmail}</div></div>
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Listing ref</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${ref}</div></div>
        <div><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;margin-bottom:5px;font-weight:700;">Received at</div><div style="font-size:14px;color:#0f172a;line-height:1.5;">${when}</div></div>
      </div>
      <p style="margin:0 0 16px;line-height:1.75;font-size:15px;color:#334155;">Fast follow-up increases conversion. We recommend reviewing this lead and contacting the prospect as soon as possible.</p>
      ${ctaBlock}
      <div style="margin-top:22px;padding-top:18px;border-top:1px solid #eef2f7;color:#64748b;font-size:13px;line-height:1.7;">If this lead was recently reassigned, you're receiving this because you are now the active owner.</div>
    </div>
    <div style="background:#f8fafc;border-top:1px solid #eef2f7;padding:18px 28px;color:#64748b;font-size:12px;line-height:1.7;">PROPQA notifies assigned users as soon as lead ownership is established.</div>
  </div>
</body>
</html>`;
}
