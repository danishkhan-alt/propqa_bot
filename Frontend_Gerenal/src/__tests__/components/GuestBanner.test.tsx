import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GuestBanner } from "@/components/chat/GuestBanner";

describe("GuestBanner", () => {
  it("renders unlock modal copy for any trigger", () => {
    render(<GuestBanner trigger="search_count" onSignUp={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: /unlock full ai features/i })).toBeInTheDocument();
    expect(screen.getByText(/trial message limit/i)).toBeInTheDocument();
  });

  it("still opens for agent_click and comparison triggers", () => {
    const { rerender } = render(<GuestBanner trigger="agent_click" onSignUp={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(<GuestBanner trigger="comparison" onSignUp={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("calls onSignUp when Sign Up is clicked", async () => {
    const onSignUp = vi.fn();
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<GuestBanner trigger="search_count" onSignUp={onSignUp} onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    expect(onSignUp).toHaveBeenCalledOnce();
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("calls onSignIn when account link is clicked", async () => {
    const onSignIn = vi.fn();
    const user = userEvent.setup();
    render(
      <GuestBanner trigger="search_count" onSignUp={vi.fn()} onSignIn={onSignIn} />,
    );

    await user.click(screen.getByRole("button", { name: /i already have an account/i }));
    expect(onSignIn).toHaveBeenCalledOnce();
  });

  it("dismisses when close is clicked", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<GuestBanner trigger="search_count" onSignUp={vi.fn()} onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(onDismiss).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
