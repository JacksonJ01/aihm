"use client";

import { forgotPasswordAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/auth-submit-button";
import { TurnstileField } from "@/components/auth/turnstile-field";
import { cn } from "@/lib/utils";
import { initialAuthActionState } from "@/lib/auth-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Link from "next/link";
import { useActionState, useMemo } from "react";

export function ForgotPasswordForm({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"div">) {
  const [state, formAction] = useActionState(forgotPasswordAction, initialAuthActionState);
  const turnstileResetSignal = useMemo(
    () => `${state.status}:${state.message ?? ""}`,
    [state.message, state.status],
  );

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      {state.status === "success" ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">Check Your Email</CardTitle>
            <CardDescription>Password reset instructions sent</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {state.message}
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">Reset Your Password</CardTitle>
            <CardDescription>
              Type in your email and we&apos;ll send you a link to reset your password.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action={formAction}>
              <div className="flex flex-col gap-6">
                <div className="grid gap-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    name="email"
                    type="email"
                    placeholder="m@example.com"
                    required
                    autoComplete="email"
                  />
                </div>
                <TurnstileField resetSignal={turnstileResetSignal} />
                {state.status === "error" ? (
                  <p className="text-sm text-red-500">{state.message}</p>
                ) : null}
                <AuthSubmitButton idleText="Send reset email" pendingText="Sending..." />
              </div>
              <div className="mt-4 text-center text-sm">
                Already have an account?{" "}
                <Link
                  href="/auth/login"
                  className="underline underline-offset-4"
                >
                  Login
                </Link>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
