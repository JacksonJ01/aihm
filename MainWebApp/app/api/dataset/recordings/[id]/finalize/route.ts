import { NextRequest, NextResponse } from "next/server";
import { finalizeRecording } from "@/lib/dataset/dataset-manager";

type RouteContext = { params: Promise<{ id: string }> };

/**
 * POST /api/dataset/recordings/[id]/finalize
 * Body: { exerciseKey: string }
 *
 * Reads frames.jsonl to compute real frame_count, duration, and fps.
 * Rewrites metadata.json with final values and appends a row to metadata.csv.
 */
export async function POST(request: NextRequest, context: RouteContext) {
  try {
    const { id: recording_id } = await context.params;
    const body = (await request.json()) as { exerciseKey: string };

    if (!body.exerciseKey) {
      return NextResponse.json(
        { error: "exerciseKey is required" },
        { status: 400 },
      );
    }

    const result = await finalizeRecording(recording_id, body.exerciseKey);
    return NextResponse.json(result);
  } catch (error) {
    console.error("[POST /api/dataset/recordings/[id]/finalize]", error);
    return NextResponse.json(
      { error: "Failed to finalize recording" },
      { status: 500 },
    );
  }
}
