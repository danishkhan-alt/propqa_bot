/**
 * RecommendationPanel.tsx — Personalised property picks panel.  🔮
 *
 * Shown in a right-panel drawer when personalizationEnabled=true in prefsStore.
 * Displays a 3-card grid of properties matched to the buyer's saved preferences.
 *
 * Props:
 *   visible        — whether the panel is shown (controlled by App.tsx)
 *   recommendations — PropertyCard[] to display (empty = show empty state)
 *   onClose        — optional close callback
 */

import React, { useState } from "react";
import {
  Sparkles,
  X,
  BookmarkPlus,
  ExternalLink,
  Home,
  Settings2,
  MapPin,
  Tag,
  BedDouble,
  Banknote,
  PenLine,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { PropertyCard } from "@/store/chatStore";
import { usePrefsStore } from "@/store/prefsStore";
import { PrefsPanel } from "./PrefsPanel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Card, CardContent, CardDescription } from "@/components/ui/card";

// ── Types ────────────────────────────────────────────────────────────────────

interface RecommendationPanelProps {
  visible: boolean;
  recommendations?: PropertyCard[];
  onClose?: () => void;
  className?: string;
}

// ── Component ────────────────────────────────────────────────────────────────

export function RecommendationPanel({
  visible,
  recommendations = [],
  onClose,
  className,
}: RecommendationPanelProps) {
  const { buyerPreferences, hasPreferences, personalizationEnabled } = usePrefsStore();
  const [prefsPanelOpen, setPrefsPanelOpen] = useState(false);

  if (!visible) return null;

  const hasRecs = recommendations.length > 0;

  const prefBadges = buyerPreferences
    ? [
        buyerPreferences.area,
        buyerPreferences.bedrooms ? `${buyerPreferences.bedrooms}BR` : null,
        buyerPreferences.propertyType,
        buyerPreferences.purpose,
      ].filter(Boolean) as string[]
    : [];

  return (
    <aside
      className={cn(
        "flex h-full w-72 shrink-0 flex-col overflow-hidden border-l bg-background",
        className,
      )}
      aria-label="Personalised recommendations"
    >
      {/* Header */}
      <div className="flex h-12 items-center justify-between border-b px-3">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          <span className="text-sm font-semibold">For You</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground"
            onClick={() => setPrefsPanelOpen(true)}
            aria-label="Set preferences"
            title="Set buyer preferences"
          >
            <Settings2 className="size-4" />
          </Button>
          {onClose && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground"
              onClick={onClose}
              aria-label="Close recommendations"
            >
              <X className="size-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Preferences summary */}
      {buyerPreferences && personalizationEnabled && (
        <div className="flex flex-wrap gap-1.5 border-b bg-muted/50 px-3 py-2">
          {prefBadges.length > 0 ? (
            prefBadges.map((badge) => (
              <Badge key={badge} variant="secondary" className="text-[10px] font-normal">
                {badge}
              </Badge>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">Searching for your ideal property</span>
          )}
        </div>
      )}

      {/* Cards / preferences summary */}
      <ScrollArea className="flex-1">
        <div className="flex flex-col gap-2 p-3">
          {hasRecs ? (
            recommendations.slice(0, 6).map((card, idx) => (
              <RecommendationCard key={card.id ?? idx} card={card} />
            ))
          ) : hasPreferences && buyerPreferences ? (
            <PreferencesSummary
              prefs={buyerPreferences}
              onEdit={() => setPrefsPanelOpen(true)}
            />
          ) : (
            <EmptyState onSetPrefs={() => setPrefsPanelOpen(true)} />
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <Separator />
      <div className="flex items-center justify-between px-4 py-3">
        <p className="text-xs text-muted-foreground">PropQA Personalisation</p>
        <Button
          variant="link"
          size="sm"
          className="h-auto px-0 text-xs"
          onClick={() => setPrefsPanelOpen(true)}
        >
          {hasPreferences ? "Edit preferences" : "Set preferences"}
        </Button>
      </div>

      {/* Preferences dialog */}
      <PrefsPanel open={prefsPanelOpen} onOpenChange={setPrefsPanelOpen} />
    </aside>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface RecommendationCardProps {
  card: PropertyCard;
}

function RecommendationCard({ card }: RecommendationCardProps) {
  const [saved, setSaved] = useState(false);

  const displayPrice =
    typeof card.price === "number"
      ? `AED ${card.price.toLocaleString()}`
      : card.price ?? "Price on request";

  const displayTitle = card.title ?? card.location ?? "Property";

  return (
    <Card className="overflow-hidden shadow-sm transition-shadow hover:shadow-md">
      {/* Image / placeholder */}
      {card.image_url ? (
        <img
          src={card.image_url}
          alt={displayTitle}
          className="h-24 w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-24 w-full items-center justify-center bg-muted">
          <Home className="size-6 text-muted-foreground/40" />
        </div>
      )}

      <CardContent className="p-2.5">
        <Badge variant="secondary" className="mb-1.5 text-[10px] font-medium">
          Matches your search
        </Badge>

        <p className="line-clamp-2 text-xs font-semibold leading-snug text-card-foreground">
          {displayTitle}
        </p>

        <p className="mt-1 text-sm font-bold text-foreground">{displayPrice}</p>

        <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
          {card.beds && <span>{card.beds} BR</span>}
          {card.area && <span>· {card.area} sqft</span>}
          {card.location && !card.title && <span>· {card.location}</span>}
        </div>

        <Separator className="my-2" />

        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-7 gap-1 px-1 text-[11px]",
              saved ? "text-foreground" : "text-muted-foreground",
            )}
            onClick={() => setSaved((s) => !s)}
            aria-label={saved ? "Unsave property" : "Save property"}
          >
            <BookmarkPlus className="size-3" />
            {saved ? "Saved" : "Save"}
          </Button>
          {card.url && (
            <a
              href={card.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-primary"
            >
              View <ExternalLink className="size-3" />
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── PreferencesSummary — shown in the panel body when prefs are set but no recs yet ──

interface PreferencesSummaryProps {
  prefs: import("@/store/prefsStore").BuyerPreferences;
  onEdit?: () => void;
}

function PreferencesSummary({ prefs, onEdit }: PreferencesSummaryProps) {
  const chips: { icon: React.ReactNode; label: string; value: string }[] = [];

  if (prefs.area) chips.push({ icon: <MapPin className="size-3" />, label: "Area", value: prefs.area });
  if (prefs.purpose)
    chips.push({
      icon: <Tag className="size-3" />,
      label: "Purpose",
      value: prefs.purpose.charAt(0).toUpperCase() + prefs.purpose.slice(1),
    });
  if (prefs.bedrooms != null)
    chips.push({ icon: <BedDouble className="size-3" />, label: "Bedrooms", value: `${prefs.bedrooms}+` });
  if (prefs.propertyType)
    chips.push({ icon: <Home className="size-3" />, label: "Type", value: prefs.propertyType });
  if (prefs.priceMin || prefs.priceMax) {
    const parts: string[] = [];
    if (prefs.priceMin) parts.push(`AED ${prefs.priceMin.toLocaleString()}`);
    if (prefs.priceMax) parts.push(`AED ${prefs.priceMax.toLocaleString()}`);
    chips.push({ icon: <Banknote className="size-3" />, label: "Budget", value: parts.join(" – ") });
  }

  return (
    <div className="flex flex-col gap-3 pt-1">
      <div className="flex items-center justify-between px-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Your Preferences
        </p>
        {onEdit && (
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-1 text-[11px]" onClick={onEdit}>
            <PenLine className="size-3" />
            Edit
          </Button>
        )}
      </div>

      {chips.length > 0 ? (
        <div className="flex flex-col gap-2">
          {chips.map((chip) => (
            <PrefChip key={chip.label} icon={chip.icon} label={chip.label} value={chip.value} />
          ))}
        </div>
      ) : null}

      <div className="flex flex-col items-center gap-1.5 px-2 pb-4 pt-2 text-center">
        <div className="flex size-8 items-center justify-center rounded-full bg-muted">
          <Sparkles className="size-4 text-muted-foreground/50" />
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Recommendations will appear as you search — your preferences are active.
        </p>
      </div>
    </div>
  );
}

function PrefChip({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted px-3 py-2">
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase leading-none tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-0.5 truncate text-xs font-semibold">{value}</p>
      </div>
    </div>
  );
}

function EmptyState({ onSetPrefs }: { onSetPrefs?: () => void }) {
  return (
    <Card className="border-dashed shadow-none">
      <CardContent className="flex flex-col items-center px-4 py-8 text-center">
        <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-muted">
          <Sparkles className="size-5 text-muted-foreground/50" />
        </div>
        <p className="mb-1 text-sm font-medium">Recommendations will appear as you search</p>
        <CardDescription className="mb-4 leading-relaxed">
          Tell us what you&apos;re looking for and we&apos;ll surface matching properties.
        </CardDescription>
        {onSetPrefs && (
          <Button variant="outline" size="sm" className="gap-1.5" onClick={onSetPrefs}>
            <Settings2 className="size-3" />
            Set Preferences
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
