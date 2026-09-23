/**
 * AuthGate — modal dialog with Sign In / Create Account / Guest tabs.
 * Opens automatically on first visit; can also be triggered from the header.
 */

import { useState } from "react";
import { LogIn, UserPlus, Zap } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { LoginForm } from "./LoginForm";
import { SignupForm } from "./SignupForm";
import { PropQABrand } from "@/components/brand/PropQABrand";
import { useAuthStore } from "@/store/authStore";

interface AuthGateProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultTab?: "login" | "register" | "guest";
  onContinueAsGuest?: () => void;
}

export function AuthGate({ open, onOpenChange, defaultTab = "login", onContinueAsGuest }: AuthGateProps) {
  const [tab, setTab] = useState<"login" | "register" | "guest">(defaultTab);
  const { continueAsGuest, clearError } = useAuthStore();

  function handleSuccess() {
    onOpenChange(false);
  }

  function handleGuest() {
    continueAsGuest();
    onContinueAsGuest?.();
    onOpenChange(false);
  }

  function handleTabChange(value: string) {
    clearError();
    setTab(value as "login" | "register" | "guest");
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="text-center">
          <PropQABrand variant="logo" className="mx-auto mb-2" />
          <DialogTitle className="text-xl">Welcome to PropQA</DialogTitle>
          <DialogDescription>
            Dubai's AI-powered property intelligence platform
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={handleTabChange}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login" className="gap-1.5">
              <LogIn className="size-3.5" />
              Sign In
            </TabsTrigger>
            <TabsTrigger value="register" className="gap-1.5">
              <UserPlus className="size-3.5" />
              Create Account
            </TabsTrigger>
          </TabsList>

          <TabsContent value="login" className="mt-4">
            <LoginForm onSuccess={handleSuccess} />
          </TabsContent>

          <TabsContent value="register" className="mt-4">
            <SignupForm onSuccess={handleSuccess} />
          </TabsContent>
        </Tabs>

        <div className="relative my-2">
          <div className="absolute inset-0 flex items-center">
            <Separator />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-background px-2 text-muted-foreground">or</span>
          </div>
        </div>

        <Button variant="outline" className="w-full gap-2" onClick={handleGuest}>
          <Zap className="size-4" />
          Continue as Guest
        </Button>

        <p className="text-center text-xs text-muted-foreground">
          Guest sessions are temporary. Sign in to save your history.
        </p>
      </DialogContent>
    </Dialog>
  );
}
