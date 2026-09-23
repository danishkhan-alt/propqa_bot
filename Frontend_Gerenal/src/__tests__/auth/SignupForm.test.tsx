import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SignupForm } from "@/components/auth/SignupForm";

const mockRegister = vi.fn();
const mockClearError = vi.fn();

vi.mock("@/store/authStore", () => ({
  useAuthStore: () => ({
    register: mockRegister,
    error: null,
    clearError: mockClearError,
    isLoading: false,
  }),
  withAuthHeaders: () => ({}),
  getAuthUserId: () => "anon-test",
  getAccessToken: () => null,
}));

describe("SignupForm", () => {
  beforeEach(() => {
    mockRegister.mockReset();
    mockClearError.mockReset();
  });

  it("renders all required fields", () => {
    render(<SignupForm />);
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
  });

  it("validates that name must be at least 2 characters", async () => {
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.type(screen.getByLabelText(/full name/i), "A");
    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.type(screen.getByLabelText(/password/i), "Password1!");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument();
    });
  });

  it("validates that password must have uppercase + number", async () => {
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.type(screen.getByLabelText(/full name/i), "Test User");
    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.type(screen.getByLabelText(/password/i), "nouppercase1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/uppercase/i)).toBeInTheDocument();
    });
  });

  it("calls register with correct data on valid submission", async () => {
    const user = userEvent.setup();
    mockRegister.mockResolvedValue(undefined);
    render(<SignupForm />);

    await user.type(screen.getByLabelText(/full name/i), "John Smith");
    await user.type(screen.getByLabelText(/email/i), "john@example.com");
    await user.type(screen.getByLabelText(/password/i), "SecurePass1!");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "John Smith",
          email: "john@example.com",
          password: "SecurePass1!",
        }),
      );
    });
  });

  it("shows terms of service text", () => {
    render(<SignupForm />);
    expect(screen.getByText(/terms of service/i)).toBeInTheDocument();
  });
});
