import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Suspense } from "react";

const ERROR_MESSAGES: Record<string, string> = {
  "invalid-link": "This confirmation link is invalid or has expired. Request a new link and try again.",
  "invalid-request": "This request could not be completed. Please retry from the previous step.",
  "profile-init-failed": "Your email was confirmed, but creating your profile record failed. Check the server log for the exact database error and verify your userProfiles schema matches the app.",
  default: "An unspecified error occurred.",
};

async function ErrorContent({
  searchParams,
}: {
  searchParams: Promise<{ code?: string }>;
}) {
  const params = await searchParams;
  const message = ERROR_MESSAGES[params?.code ?? ""] ?? ERROR_MESSAGES.default;

  return (
    <p className="text-sm text-muted-foreground">
      {message}
    </p>
  );
}

export default function Page({
  searchParams,
}: {
  searchParams: Promise<{ code?: string }>;
}) {
  return (
    <div className="flex min-h-svh w-full items-center justify-center p-6 md:p-10">
      <div className="w-full max-w-sm">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-2xl">
                Sorry, something went wrong.
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Suspense
                fallback={
                  <p className="text-sm text-muted-foreground">
                    Loading error details.
                  </p>
                }
              >
                <ErrorContent searchParams={searchParams} />
              </Suspense>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
