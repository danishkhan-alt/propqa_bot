/**
 * MemoryPanel — shows rolling summary, knowledge slots, and LTM recall hits.
 */

import { useState, useEffect, useCallback } from "react";
import { X, RefreshCw, Trash2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/authStore";

interface MemoryPanelProps {
  isOpen: boolean;
  sessionId: string | null;
  summary?: string;
  knowledge?: Record<string, unknown>;
  recallHits?: unknown[];
  contextUsage?: { fraction?: number; prompt_tokens?: number; budget?: number } | null;
  onClose?: () => void;
  onCompact?: () => void;
  onForgetAll?: () => void;
  className?: string;
}

export function MemoryPanel({
  isOpen,
  sessionId,
  summary,
  knowledge,
  recallHits,
  contextUsage,
  onClose,
  onCompact,
  onForgetAll,
  className,
}: MemoryPanelProps) {
  const { isAuthenticated } = useAuthStore();

  if (!isOpen) return null;

  const fraction = contextUsage?.fraction ?? 0;
  const pct = Math.round(fraction * 100);

  return (
    <aside className={cn("flex w-72 shrink-0 flex-col border-l bg-background", className)}>
      {/* Header */}
      <div className="flex h-12 items-center justify-between border-b px-3">
        <span className="text-sm font-semibold">Memory & Context</span>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-4 p-3">
          {/* Context usage */}
          {contextUsage && (
            <section>
              <div className="flex items-center justify-between text-xs font-medium mb-1.5">
                <span>Context Usage</span>
                <span className={cn("font-semibold", pct > 80 ? "text-amber-600" : "text-muted-foreground")}>
                  {pct}%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full context-bar-fill",
                    pct > 80 ? "bg-amber-500" : pct > 60 ? "bg-yellow-500" : "bg-emerald-500",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {onCompact && (
                <Button size="sm" variant="outline" className="mt-2 h-6 w-full text-[10px]" onClick={onCompact}>
                  <RefreshCw className="mr-1 size-3" />
                  Compact Now
                </Button>
              )}
            </section>
          )}

          <Separator />

          {/* Rolling summary */}
          {summary && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary</h4>
              <p className="text-xs leading-relaxed text-muted-foreground">{summary}</p>
            </section>
          )}

          {/* Knowledge slots */}
          {knowledge && Object.keys(knowledge).length > 0 && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Remembered</h4>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(knowledge).map(([k, v]) => (
                  <div key={k} className="rounded-md border bg-muted/50 px-2 py-1 text-[11px]">
                    <span className="font-medium">{k}:</span>{" "}
                    <span className="text-muted-foreground">{String(v)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* LTM recall hits */}
          {recallHits && recallHits.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Long-term Memory ({recallHits.length})
              </h4>
              <div className="space-y-1">
                {recallHits.map((hit: unknown, i) => {
                  const h = hit as Record<string, unknown>;
                  return (
                    <div key={i} className="rounded-md border bg-muted/30 px-2 py-1.5 text-[11px]">
                      {h.fact ? String(h.fact) : JSON.stringify(h).slice(0, 80)}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Saved searches (authenticated only) */}
          {!isAuthenticated && (
            <section>
              <div className="flex items-center gap-2 rounded-md border border-dashed p-3 text-xs text-muted-foreground">
                <Lock className="size-4 shrink-0" />
                <span>Sign in to save searches and access long-term memory across sessions.</span>
              </div>
            </section>
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      {onForgetAll && (
        <div className="border-t p-3">
          <Button
            size="sm"
            variant="ghost"
            className="w-full gap-2 text-xs text-destructive hover:text-destructive"
            onClick={onForgetAll}
          >
            <Trash2 className="size-3.5" />
            Forget This Session
          </Button>
        </div>
      )}
    </aside>
  );
}
