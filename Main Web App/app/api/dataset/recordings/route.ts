import { NextRequest, NextResponse } from "next/server";
import { createRecording, listRecordings } from "@/lib/dataset/dataset-manager";
import type { CreateRecordingRequest } from "@/lib/dataset/types";

/** POST /api/dataset/recordings — create a new recording folder + metadata.json */
export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as CreateRecordingRequest;

    if (!body.metadata?.exerciseKey) {
      return NextResponse.json(
        { error: "exerciseKey is required" },
        { status: 400 },
      );
    }

    const result = await createRecording(body.metadata);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    console.error("[POST /api/dataset/recordings]", error);
    return NextResponse.json(
      { error: "Failed to create recording" },
      { status: 500 },
    );
  }
}

/** GET /api/dataset/recordings — list all finalized recordings from metadata.csv */
export async function GET() {
  try {
    const recordings = await listRecordings();
    return NextResponse.json({ recordings });
  } catch (error) {
    console.error("[GET /api/dataset/recordings]", error);
    return NextResponse.json(
      { error: "Failed to list recordings" },
      { status: 500 },
    );
  }
}
