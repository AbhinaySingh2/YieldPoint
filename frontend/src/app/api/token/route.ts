import {
  AccessToken,
  RoomAgentDispatch,
  RoomConfiguration,
} from "livekit-server-sdk";
import { NextResponse } from "next/server";

const AGENT_NAME = "floor-tech-local";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const roomName =
      searchParams.get("room") ||
      `yieldpoint-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const participantName =
      searchParams.get("name") ||
      `operator-${Math.floor(Math.random() * 1000)}`;

    const apiKey = process.env.LIVEKIT_API_KEY;
    const apiSecret = process.env.LIVEKIT_API_SECRET;

    if (!apiKey || !apiSecret) {
      return NextResponse.json(
        { error: "Server misconfigured. Missing LiveKit credentials." },
        { status: 500 }
      );
    }

    const at = new AccessToken(apiKey, apiSecret, {
      identity: participantName,
    });

    at.addGrant({
      roomJoin: true,
      room: roomName,
      canPublish: true,
      canPublishData: true,
      canSubscribe: true,
    });

    // Explicit agent dispatch — applied when this participant creates the room.
    // Must match WorkerOptions(agent_name=...) in agent.py.
    at.roomConfig = new RoomConfiguration({
      agents: [
        new RoomAgentDispatch({
          agentName: AGENT_NAME,
          metadata: JSON.stringify({
            product: "YieldPoint",
            role: "floor-technician",
          }),
        }),
      ],
    });

    const token = await at.toJwt();
    return NextResponse.json({
      token,
      room: roomName,
      agent: AGENT_NAME,
      serverUrl: process.env.NEXT_PUBLIC_LIVEKIT_URL ?? null,
    });
  } catch (error) {
    console.error("Failed to generate token", error);
    return NextResponse.json(
      { error: "Failed to generate token" },
      { status: 500 }
    );
  }
}
