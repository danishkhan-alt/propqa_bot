/**
 * PropQABrand — shared logo/icon from media/Icon.svg and media/Logo.svg.
 *
 * Variants:
 *   icon   — red mark only (header, favicon-scale)
 *   logo   — full wordmark (welcome, auth dialog)
 */

import { cn } from "@/lib/utils";

const ICON_SRC = "/propqa-icon.svg";
const LOGO_SRC = "/propqa-logo.svg";
const LOGO_DARK_SRC = "/logo-header-white.svg";

interface PropQABrandProps {
  variant?: "icon" | "logo";
  className?: string;
  /** Show "Dubai Property AI" tagline below the logo (logo variant only) */
  showTagline?: boolean;
}

export function PropQABrand({
  variant = "logo",
  className,
  showTagline = false,
}: PropQABrandProps) {
  if (variant === "icon") {
    return (
      <img
        src={ICON_SRC}
        alt="PropQA"
        className={cn("size-6 shrink-0 object-contain", className)}
        width={24}
        height={24}
      />
    );
  }

  // logo — centered welcome / auth
  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <img
        src={LOGO_SRC}
        alt="PropQA"
        className="h-14 w-auto max-w-[200px] object-contain dark:hidden sm:h-16"
        height={56}
      />
      <img
        src={LOGO_DARK_SRC}
        alt="PropQA"
        className="hidden h-14 w-auto max-w-[200px] object-contain dark:block sm:h-16"
        height={56}
      />
      {showTagline && (
        <p className="text-sm text-muted-foreground">Dubai Property AI</p>
      )}
    </div>
  );
}
