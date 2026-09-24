import { profileChips, useSessionProfileStore } from "@/store/sessionProfileStore";

export function SessionStrip() {
  const profile = useSessionProfileStore((state) => state.profile);
  const merge = useSessionProfileStore((state) => state.merge);
  const chips = profileChips(profile);
  if (!chips.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-t border-[#E8ECF3] bg-white px-3 py-2">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          aria-label={`Remove ${chip.label}`}
          onClick={() => merge({ [chip.key]: null })}
          className="rounded-full border border-[#E8ECF3] bg-[#F7F8FA] px-2.5 py-1 text-xs text-[#141B34]"
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
