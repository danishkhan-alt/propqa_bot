import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Header } from "@/components/layout/Header";

// Set up mock for authStore
let mockIsAuthenticated = false;
let mockIsGuest = true;
let mockUser: { id: string; email: string; name: string; role: "user" | "admin" } | null = null;
const mockLogout = vi.fn();

vi.mock("@/store/authStore", () => ({
  useAuthStore: () => ({
    isAuthenticated: mockIsAuthenticated,
    isGuest: mockIsGuest,
    user: mockUser,
    logout: mockLogout,
  }),
  withAuthHeaders: () => ({}),
  getAuthUserId: () => "anon-test",
  getAccessToken: () => null,
}));

// Mock dropdown-menu for UserMenu
vi.mock("@radix-ui/react-dropdown-menu", () => ({
  Root: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Trigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Portal: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Content: ({ children }: { children: React.ReactNode }) => <div role="menu">{children}</div>,
  Item: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) => (
    <button role="menuitem" onClick={onClick}>{children}</button>
  ),
  Label: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Separator: () => <hr />,
  Group: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Sub: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  RadioGroup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe("Header (guest mode)", () => {
  beforeEach(() => {
    mockIsAuthenticated = false;
    mockIsGuest = true;
    mockUser = null;
    mockLogout.mockReset();
  });

  it("shows Sign Up for guests", () => {
    render(<Header />);
    expect(screen.getByRole("button", { name: /sign up/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /agent portal/i })).not.toBeInTheDocument();
  });

  it("does not show Sign In in the header chrome", () => {
    render(<Header />);
    expect(screen.queryByRole("button", { name: /^sign in$/i })).not.toBeInTheDocument();
  });

  it("calls onRegister when Sign Up is clicked", async () => {
    const onRegister = vi.fn();
    const user = userEvent.setup();
    render(<Header onRegister={onRegister} />);
    await user.click(screen.getByRole("button", { name: /sign up/i }));
    expect(onRegister).toHaveBeenCalledOnce();
  });

  it("shows PropQA logo via alt text", () => {
    render(<Header />);
    expect(screen.getByAltText(/propqa/i)).toBeInTheDocument();
  });

  it("never renders the personalisation/recommendations toggle for guests", () => {
    render(<Header />);
    expect(screen.queryByRole("button", { name: /recommendations panel/i })).not.toBeInTheDocument();
  });

  it("does not render theme toggle or Clear Chat in the header", () => {
    render(<Header onNewChat={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /toggle theme/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /clear chat/i })).not.toBeInTheDocument();
  });
});

describe("Header (authenticated mode)", () => {
  beforeEach(() => {
    mockIsAuthenticated = true;
    mockIsGuest = false;
    mockUser = { id: "u1", email: "demo@propqa.ai", name: "Demo User", role: "user" };
  });

  it("shows user avatar initials instead of Sign Up", () => {
    render(<Header />);
    expect(screen.queryByRole("button", { name: /sign up/i })).not.toBeInTheDocument();
  });

  it("renders the recommendations toggle when onTogglePersonalization is provided", () => {
    render(<Header onTogglePersonalization={vi.fn()} personalizationEnabled={false} />);
    expect(screen.getByRole("button", { name: /show recommendations panel/i })).toBeInTheDocument();
  });
});
