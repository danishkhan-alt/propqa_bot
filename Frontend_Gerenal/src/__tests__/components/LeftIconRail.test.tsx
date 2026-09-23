import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeftIconRail } from "@/components/layout/LeftIconRail";
import type { SessionSummary } from "@/api/sessionApi";

const listSessions = vi.fn();
const forgetSession = vi.fn();
const forgetSessions = vi.fn();

vi.mock("@/api/sessionApi", () => ({
  listSessions: (...args: unknown[]) => listSessions(...args),
  forgetSession: (...args: unknown[]) => forgetSession(...args),
  forgetSessions: (...args: unknown[]) => forgetSessions(...args),
}));

vi.mock("@/store/authStore", () => ({
  useAuthStore: () => ({ userId: "user-1" }),
}));

const SESSIONS: SessionSummary[] = [
  {
    session_id: "s1",
    title: "142 active two-bedroom options across the Dubai Marina community.",
    user_turns: 3,
    created_at: "2026-09-01T08:00:00Z",
    last_active: "2026-09-01T09:00:00Z",
  },
  {
    session_id: "s2",
    title: "Villas in Palm Jumeirah",
    user_turns: 1,
    created_at: "2026-09-01T07:00:00Z",
    last_active: "2026-09-01T07:30:00Z",
  },
];

describe("LeftIconRail", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    try {
      localStorage.removeItem("propqa_theme");
    } catch {
      /* ignore */
    }
    listSessions.mockReset();
    forgetSession.mockReset();
    forgetSessions.mockReset();
    listSessions.mockResolvedValue(SESSIONS);
    forgetSession.mockResolvedValue(true);
    forgetSessions.mockResolvedValue(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  afterEach(() => {
    document.documentElement.classList.remove("dark");
    vi.restoreAllMocks();
  });

  it("toggles the dark class when theme button is clicked (collapsed)", async () => {
    const user = userEvent.setup();
    render(<LeftIconRail />);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    await user.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    await user.click(screen.getByRole("button", { name: /toggle theme/i }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("calls onNewChat from the collapsed icon rail", async () => {
    const onNewChat = vi.fn();
    const user = userEvent.setup();
    render(<LeftIconRail onNewChat={onNewChat} />);
    await user.click(screen.getByRole("button", { name: /new chat/i }));
    expect(onNewChat).toHaveBeenCalledOnce();
  });

  it("disables New Chat when onNewChat is omitted", () => {
    render(<LeftIconRail />);
    expect(screen.getByRole("button", { name: /new chat/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /toggle theme/i })).toBeEnabled();
  });

  it("calls onExpandedChange when the sidebar button is clicked", async () => {
    const onExpandedChange = vi.fn();
    const user = userEvent.setup();
    render(<LeftIconRail onExpandedChange={onExpandedChange} />);
    await user.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(onExpandedChange).toHaveBeenCalledWith(true);
  });

  it("disables sidebar toggle when onExpandedChange is omitted", () => {
    render(<LeftIconRail />);
    expect(screen.getByRole("button", { name: /toggle sidebar/i })).toBeDisabled();
  });

  it("renders New Chat, Recent, and session titles when expanded", async () => {
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        currentSessionId="s2"
        onNewChat={vi.fn()}
        onSelectSession={vi.fn()}
        onForgetSession={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /new chat/i })).toHaveTextContent("New Chat");
    expect(screen.getByText("Recent")).toBeInTheDocument();
    expect(screen.getByLabelText(/search conversations/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTitle(/dubai marina/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    expect(listSessions).toHaveBeenCalled();
  });

  it("labels the active session with the first-user hint, not a later API title", async () => {
    listSessions.mockResolvedValue([
      {
        session_id: "s-active",
        title: "4 bath",
        user_turns: 3,
        created_at: "2026-09-01T10:00:00Z",
        last_active: "2026-09-01T11:00:00Z",
      },
    ]);

    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        currentSessionId="s-active"
        sessionTitleHint="show 3 bed apartment"
        onSelectSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTitle(/show 3 bed apartment/i)).toBeInTheDocument();
    });
    expect(screen.queryByTitle(/^4 bath$/i)).not.toBeInTheDocument();
  });

  it("shows a visible delete button on each recent row", async () => {
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        onForgetSession={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /delete.*dubai marina/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /delete.*palm jumeirah/i })).toBeVisible();
  });

  it("deletes one conversation without passing user_id and calls onForgetSession", async () => {
    const onForgetSession = vi.fn();
    const user = userEvent.setup();
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        onForgetSession={onForgetSession}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /delete.*palm jumeirah/i }));

    expect(forgetSession).toHaveBeenCalledWith("s2");
    expect(forgetSession.mock.calls[0]).toHaveLength(1);
    expect(onForgetSession).toHaveBeenCalledWith("s2");
    await waitFor(() => {
      expect(screen.queryByText(/palm jumeirah/i)).not.toBeInTheDocument();
    });
  });

  it("adds the active session to Recent when streaming finishes", async () => {
    listSessions
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          session_id: "s-new",
          title: "show the 5 bed villa",
          user_turns: 1,
          created_at: "2026-09-01T10:00:00Z",
          last_active: "2026-09-01T10:00:00Z",
        },
      ]);

    const { rerender } = render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        currentSessionId="s-new"
        isStreaming
        sessionTitleHint="show the 5 bed villa"
        onForgetSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalled();
    });
    expect(screen.queryByText(/5 bed villa/i)).not.toBeInTheDocument();

    rerender(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        currentSessionId="s-new"
        isStreaming={false}
        sessionTitleHint="show the 5 bed villa"
        onForgetSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/5 bed villa/i)).toBeInTheDocument();
    });
  });

  it("calls onNewChat from the expanded New Chat pill", async () => {
    const onNewChat = vi.fn();
    const user = userEvent.setup();
    render(
      <LeftIconRail expanded onExpandedChange={vi.fn()} onNewChat={onNewChat} />,
    );
    await user.click(screen.getByRole("button", { name: /new chat/i }));
    expect(onNewChat).toHaveBeenCalledOnce();
  });

  it("filters recent sessions by search query", async () => {
    const user = userEvent.setup();
    render(
      <LeftIconRail expanded onExpandedChange={vi.fn()} onSelectSession={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/search conversations/i), "palm");
    expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    expect(screen.queryByTitle(/dubai marina/i)).not.toBeInTheDocument();
  });

  it("calls onSelectSession when a recent item is clicked", async () => {
    const onSelectSession = vi.fn();
    const user = userEvent.setup();
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        onSelectSession={onSelectSession}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    });
    await user.click(screen.getByText(/palm jumeirah/i));
    expect(onSelectSession).toHaveBeenCalledWith("s2");
  });

  it("collapses the panel via the header toggle", async () => {
    const onExpandedChange = vi.fn();
    const user = userEvent.setup();
    render(<LeftIconRail expanded onExpandedChange={onExpandedChange} />);
    await user.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(onExpandedChange).toHaveBeenCalledWith(false);
  });

  it("Clear all forgets every listed sid and calls onForgetAll", async () => {
    const onForgetAll = vi.fn();
    const user = userEvent.setup();
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        onForgetSession={vi.fn()}
        onForgetAll={onForgetAll}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/palm jumeirah/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /clear all conversations/i }));

    expect(forgetSessions).toHaveBeenCalledWith(["s1", "s2"]);
    expect(forgetSession).not.toHaveBeenCalled();
    expect(onForgetAll).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });
  });

  it("disables Clear all when there are no conversations", async () => {
    listSessions.mockResolvedValue([]);
    render(
      <LeftIconRail
        expanded
        onExpandedChange={vi.fn()}
        onForgetSession={vi.fn()}
        onForgetAll={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /clear all conversations/i })).toBeDisabled();
  });
});
