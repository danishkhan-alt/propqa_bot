/**
 * PrefsPanel.tsx — Buyer preferences configuration dialog.  🔮
 *
 * Opened from the RecommendationPanel empty state or the Sparkles button.
 * Lets the user set area, bedrooms, property type, purpose, and price range.
 * Persists to prefsStore (localStorage).
 */

import { useState, useEffect } from "react";
import { Sparkles, X, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePrefsStore, type BuyerPreferences } from "@/store/prefsStore";
import { useAuthStore, getAuthUserId } from "@/store/authStore";
import { savePreferences, deletePreferences } from "@/api/preferencesApi";
import { getActiveSessionId } from "@/hooks/useChat";

// ── Types ────────────────────────────────────────────────────────────────────

interface PrefsPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// ── Option sets ──────────────────────────────────────────────────────────────

const PROPERTY_TYPES = ["Apartment", "Villa", "Townhouse", "Studio", "Penthouse", "Duplex"];
const PURPOSES = [
  { value: "buy", label: "Buy" },
  { value: "rent", label: "Rent" },
] as const;
const BEDROOM_OPTS = [null, 1, 2, 3, 4, 5] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function PrefsPanel({ open, onOpenChange }: PrefsPanelProps) {
  // Buyer preferences are a signed-in-only feature. All entry points that
  // open this dialog are already gated on isAuthenticated (Header's
  // Sparkles toggle, RecommendationPanel, the /dashboard route), but guard
  // the save action here too rather than trusting callers.
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const {
    buyerPreferences,
    savedSearches,
    personalizationEnabled,
    hasPreferences,
    setPreferences,
    clearPreferences,
    clearSavedSearches,
    removeSavedSearch,
    setPersonalizationEnabled,
  } = usePrefsStore();

  const [area, setArea] = useState(buyerPreferences?.area ?? "");
  const [bedrooms, setBedrooms] = useState<number | null>(buyerPreferences?.bedrooms ?? null);
  const [propertyType, setPropertyType] = useState(buyerPreferences?.propertyType ?? "");
  const [purpose, setPurpose] = useState<"buy" | "rent" | null>(buyerPreferences?.purpose ?? null);
  const [priceMin, setPriceMin] = useState(String(buyerPreferences?.priceMin ?? ""));
  const [priceMax, setPriceMax] = useState(String(buyerPreferences?.priceMax ?? ""));

  useEffect(() => {
    if (!open) return;
    setArea(buyerPreferences?.area ?? "");
    setBedrooms(buyerPreferences?.bedrooms ?? null);
    setPropertyType(buyerPreferences?.propertyType ?? "");
    setPurpose(buyerPreferences?.purpose ?? null);
    setPriceMin(String(buyerPreferences?.priceMin ?? ""));
    setPriceMax(String(buyerPreferences?.priceMax ?? ""));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSave() {
    if (!isAuthenticated) {
      onOpenChange(false);
      return;
    }
    const prefs: Partial<BuyerPreferences> = {
      area: area.trim() || undefined,
      bedrooms: bedrooms,
      propertyType: propertyType || undefined,
      purpose: purpose,
      priceMin: priceMin ? Number(priceMin) : undefined,
      priceMax: priceMax ? Number(priceMax) : undefined,
    };
    setPreferences(prefs);
    // Mirror into the Redis-backed profile (fire-and-forget) so preferences
    // are durable across devices/browsers and a server restart, not just
    // this browser's localStorage.
    const userId = getAuthUserId();
    if (userId) {
      void savePreferences({ userId, preferences: prefs });
    }
    onOpenChange(false);
  }

  function handleClear() {
    clearPreferences();
    setArea("");
    setBedrooms(null);
    setPropertyType("");
    setPurpose(null);
    setPriceMin("");
    setPriceMax("");
    // Clear the Redis-backed mirror too (fire-and-forget) — otherwise the
    // old values survive server-side and silently come back on the next
    // chat turn's boot-time hydration or a GET from another device/browser,
    // even though the user just reset the panel here. Also flushes this
    // tab's session-level filter-spec carry-forward so an already-applied
    // preference (e.g. area/type from an earlier turn this session) stops
    // being replayed on the very next vague message.
    const userId = getAuthUserId();
    if (isAuthenticated && userId) {
      void deletePreferences({ userId, sessionId: getActiveSessionId() });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-full bg-muted">
              <Sparkles className="size-4 text-primary" />
            </div>
            <DialogTitle>My Property Preferences</DialogTitle>
          </div>
          <DialogDescription>
            Set your preferences to get personalised property recommendations as you search.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Area / Location */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pref-area">Preferred Area / Community</Label>
            <Input
              id="pref-area"
              placeholder="e.g. Downtown Dubai, JBR, Palm Jumeirah"
              value={area}
              onChange={(e) => setArea(e.target.value)}
            />
          </div>

          {/* Purpose */}
          <div className="flex flex-col gap-1.5">
            <Label>Purpose</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              className="w-full"
              value={purpose ?? ""}
              onValueChange={(v) => {
                if (v) setPurpose(v as "buy" | "rent");
              }}
            >
              {PURPOSES.map((p) => (
                <ToggleGroupItem
                  key={p.value}
                  value={p.value}
                  className="flex-1"
                  onClick={() => {
                    if (purpose === p.value) setPurpose(null);
                  }}
                >
                  {p.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          {/* Bedrooms */}
          <div className="flex flex-col gap-1.5">
            <Label>Bedrooms</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              className="flex-wrap justify-start"
              value={bedrooms === null ? "any" : String(bedrooms)}
              onValueChange={(v) => {
                if (v === "any") setBedrooms(null);
                else if (v) setBedrooms(Number(v));
              }}
            >
              {BEDROOM_OPTS.map((b) => {
                const value = b === null ? "any" : String(b);
                return (
                  <ToggleGroupItem
                    key={value}
                    value={value}
                    className="min-w-10"
                    onClick={() => {
                      if (bedrooms === b) setBedrooms(null);
                    }}
                  >
                    {b === null ? "Any" : `${b}+`}
                  </ToggleGroupItem>
                );
              })}
            </ToggleGroup>
          </div>

          {/* Property type */}
          <div className="flex flex-col gap-1.5">
            <Label>Property Type</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              className="flex-wrap justify-start"
              value={propertyType || ""}
              onValueChange={(v) => {
                if (v) setPropertyType(v);
              }}
            >
              {PROPERTY_TYPES.map((t) => (
                <ToggleGroupItem
                  key={t}
                  value={t}
                  className="rounded-full px-3 text-xs"
                  onClick={() => {
                    if (propertyType === t) setPropertyType("");
                  }}
                >
                  {t}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          {/* Price range */}
          <div className="flex flex-col gap-1.5">
            <Label>Budget (AED)</Label>
            <div className="flex items-center gap-2">
              <Input
                placeholder="Min"
                value={priceMin}
                onChange={(e) => setPriceMin(e.target.value.replace(/\D/g, ""))}
                className="text-sm"
              />
              <span className="text-sm text-muted-foreground">–</span>
              <Input
                placeholder="Max"
                value={priceMax}
                onChange={(e) => setPriceMax(e.target.value.replace(/\D/g, ""))}
                className="text-sm"
              />
            </div>
          </div>

          {/* Personalization toggle */}
          <Card>
            <CardContent className="flex items-center justify-between gap-4 p-3">
              <div>
                <p className="text-sm font-medium">Show Recommendations</p>
                <p className="text-xs text-muted-foreground">
                  Display the personalised panel during search
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Label htmlFor="prefs-personalization-switch" className="sr-only">
                  Show Recommendations
                </Label>
                <Switch
                  id="prefs-personalization-switch"
                  checked={personalizationEnabled}
                  onCheckedChange={setPersonalizationEnabled}
                />
              </div>
            </CardContent>
          </Card>

          {/* Saved searches */}
          {savedSearches.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label>Saved Searches ({savedSearches.length})</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-destructive hover:text-destructive"
                  onClick={clearSavedSearches}
                >
                  Clear all
                </Button>
              </div>
              <div className="flex max-h-32 flex-col gap-1 overflow-y-auto rounded-lg border p-1">
                {savedSearches.map((s) => (
                  <div
                    key={s.searchId}
                    className="flex items-center justify-between rounded-md bg-muted/50 px-2.5 py-1.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium">{s.label}</p>
                      <p className="truncate text-[10px] text-muted-foreground">{s.query}</p>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="ml-2 size-7 shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={() => removeSavedSearch(s.searchId)}
                      aria-label={`Remove saved search ${s.label}`}
                    >
                      <X className="size-3" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          {hasPreferences && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="gap-1.5 text-xs text-muted-foreground"
            >
              <Trash2 className="size-3" />
              Reset
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave}>
            Save Preferences
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
