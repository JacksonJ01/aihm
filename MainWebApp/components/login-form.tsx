"use client";

import { loginAction } from "@/app/auth/actions";
import { AuthSubmitButton } from "@/components/auth/auth-submit-button";
import { TurnstileField } from "@/components/auth/turnstile-field";
import { cn, getSafeAppPath } from "@/lib/utils";
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
import { useSearchParams } from "next/navigation";

type LoginFormProps = React.ComponentPropsWithoutRef<"div"> & {
  nextPath?: string;
};

function LoginFormContent({
  className,
  nextPath,
  ...props
}: LoginFormProps) {
  const [state, formAction] = useActionState(loginAction, initialAuthActionState);
  const turnstileResetSignal = useMemo(
    () => `${state.status}:${state.message ?? ""}`,
    [state.message, state.status],
  );
  const safeNextPath = getSafeAppPath(nextPath) ?? "/";

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">Login</CardTitle>
          <CardDescription>
            Enter your email or username below to log in to your account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={formAction}>
            <input type="hidden" name="next" value={safeNextPath} />
            <div className="flex flex-col gap-6">
              <div className="grid gap-2">
                <Label htmlFor="email">Email or Username</Label>
                <Input
                  id="email"
                  name="email"
                  type="text"
                  placeholder="m@example.com or your_username"
                  required
                  autoComplete="username"
                />
              </div>
              <div className="grid gap-2">
                <div className="flex items-center">
                  <Label htmlFor="password">Password</Label>
                  <Link
                    href="/auth/forgot-password"
                    className="ml-auto inline-block text-sm underline-offset-4 hover:underline"
                  >
                    Forgot your password?
                  </Link>
                </div>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  required
                  autoComplete="current-password"
                />
              </div>
              <TurnstileField resetSignal={turnstileResetSignal} />
              {state.status === "error" ? (
                <p className="text-sm text-red-500">{state.message}</p>
              ) : null}
              <AuthSubmitButton idleText="Login" pendingText="Logging in..." />
            </div>
            <div className="mt-4 text-center text-sm">
              Don&apos;t have an account?{" "}
              <Link
                href="/auth/sign-up"
                className="underline underline-offset-4"
              >
                Sign up
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export function LoginForm(props: LoginFormProps) {
  const searchParams = useSearchParams();

  return <LoginFormContent {...props} nextPath={props.nextPath ?? searchParams.get("next") ?? undefined} />;
}

export function LoginFormFallback(props: Omit<LoginFormProps, "nextPath">) {
  return <LoginFormContent {...props} nextPath="/" />;
}
