import { NextRequest, NextResponse } from "next/server";
import { appendFrames } from "@/lib/dataset/dataset-manager";
import type { AppendFramesRequest } from "@/lib/dataset/types";

type RouteContext = { params: Promise<{ id: string }> };

/**
 * POST /api/dataset/recordings/[id]/frames
 * Body: { frames: FrameData[], exerciseKey: string }
 *
 * Appends frames as individual JSON lines to frames.jsonl.
 * Safe to call multiple times — always appends, never overwrites.
 */
export async function POST(request: NextRequest, context: RouteContext) {
  try {
    const { id: recording_id } = await context.params;
    const body = (await request.json()) as AppendFramesRequest & { exerciseKey: string };

    if (!body.exerciseKey) {
      return NextResponse.json(
        { error: "exerciseKey is required" },
        { status: 400 },
      );
    }

    if (!Array.isArray(body.frames) || body.frames.length === 0) {
      return NextResponse.json(
        { error: "frames array is required and must not be empty" },
        { status: 400 },
      );
    }

    const result = await appendFrames(recording_id, body.exerciseKey, body.frames);
    return NextResponse.json(result);
  } catch (error) {
    console.error("[POST /api/dataset/recordings/[id]/frames]", error);
    return NextResponse.json(
      { error: "Failed to append frames" },
      { status: 500 },
    );
  }
}
