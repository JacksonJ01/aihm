"use client";

import { updatePasswordAction } from "@/app/auth/actions";
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
import { useActionState, useMemo } from "react";

export function UpdatePasswordForm({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"div">) {
  const [state, formAction] = useActionState(updatePasswordAction, initialAuthActionState);
  const turnstileResetSignal = useMemo(
    () => `${state.status}:${state.message ?? ""}`,
    [state.message, state.status],
  );

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Reset Your Password</CardTitle>
          <CardDescription>
            Enter a strong new password to finish securing your account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={formAction}>
            <div className="flex flex-col gap-6">
              <div className="grid gap-2">
                <Label htmlFor="password">New password</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="New password"
                  required
                  autoComplete="new-password"
                  minLength={10}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="repeat-password">Confirm new password</Label>
                <Input
                  id="repeat-password"
                  name="repeat_password"
                  type="password"
                  placeholder="Confirm new password"
                  required
                  autoComplete="new-password"
                  minLength={10}
                />
              </div>
              <TurnstileField resetSignal={turnstileResetSignal} />
              {state.status === "error" ? (
                <p className="text-sm text-red-500">{state.message}</p>
              ) : null}
              <AuthSubmitButton idleText="Save new password" pendingText="Saving..." />
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
