"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  BarVisualizer,
  useVoiceAssistant,
  useLocalParticipant,
  useTrackTranscription,
  useRoomContext,
} from "@livekit/components-react";
import { Track, RoomEvent } from "livekit-client";
import type { ReceivedTranscriptionSegment } from "@livekit/components-core";

/* ── Static machine data (mirrors MACHINE_DB in agent.py) ── */
const MACHINES = [
  { id: "CNC-4401", status: "nominal" },
  { id: "CNC-4402", status: "warning" },
  { id: "PRESS-801", status: "nominal" },
  { id: "PRESS-802", status: "critical" },
  { id: "CNC-4403", status: "offline" },
] as const;

export default function Home() {
  const [token, setToken] = useState<string>("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string>("");

  const connectToAgent = useCallback(async () => {
    try {
      setIsConnecting(true);
      setError("");

      const response = await fetch("/api/token");
      if (!response.ok) {
        throw new Error("Failed to fetch token");
      }

      const data = await response.json();
      if (data.error) {
        throw new Error(data.error);
      }

      setToken(data.token);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Connection failed";
      setError(message);
      console.error(e);
    } finally {
      setIsConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setToken("");
  }, []);

  return (
    <main className="app-container">
      <div className="header">
        <h1>YieldPoint</h1>
        <p>Intelligent Floor-Technician Assistant</p>
      </div>

      {!token ? (
        <div className="connect-panel">
          <h2>Ready to assist</h2>
          <p className="subtitle">
            Establish a secure voice connection with the maintenance registry.
            Speak naturally — the agent handles the rest.
          </p>
          <button
            className={`connect-btn ${isConnecting ? "connecting" : ""}`}
            onClick={connectToAgent}
            disabled={isConnecting}
          >
            {isConnecting ? "Connecting…" : "Connect to Agent"}
          </button>
          {error && <p className="error-message">{error}</p>}
          <MachineStatusBar />
        </div>
      ) : (
        <LiveKitRoom
          token={token}
          serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL}
          connect={true}
          audio={true}
          video={false}
          onDisconnected={disconnect}
          className="active-room"
        >
          <RoomAudioRenderer />

          <div className="room-header">
            <button className="disconnect-btn" onClick={disconnect}>
              ✕ Disconnect
            </button>
          </div>

          <AgentVisualizer />

          <TranscriptPanel />

          <VoiceAssistantControlBar />

          <MachineStatusBar />
        </LiveKitRoom>
      )}
    </main>
  );
}

/* ── Agent Visualizer ──────────────────────────────── */
function AgentVisualizer() {
  const { state, audioTrack } = useVoiceAssistant();

  const stateClass =
    state === "speaking"
      ? "state-speaking"
      : state === "listening"
        ? "state-listening"
        : "state-idle";

  const stateLabel =
    state === "speaking"
      ? "Agent Speaking"
      : state === "listening"
        ? "Listening"
        : "Standing By";

  return (
    <div className={`visualizer-container ${stateClass}`}>
      <div className="agent-visualizer">
        <BarVisualizer
          state={state}
          barCount={7}
          trackRef={audioTrack}
          options={{ minHeight: 24 }}
        />
        <div className={`agent-state ${stateClass}`}>{stateLabel}</div>
      </div>
    </div>
  );
}

/* ── Transcript Panel ──────────────────────────────── */

interface DisplayMessage {
  /** Unique key for React */
  key: string;
  role: "agent" | "user";
  text: string;
  isFinal: boolean;
  time: number;
}

/**
 * Converts raw ReceivedTranscriptionSegment[] into DisplayMessage[].
 * Only keeps the most recent non-final segment; all final ones are kept.
 */
function segmentsToMessages(
  segments: ReceivedTranscriptionSegment[],
  role: "agent" | "user",
): DisplayMessage[] {
  const msgs: DisplayMessage[] = [];
  for (const seg of segments) {
    if (seg.text.trim() === "") continue;
    msgs.push({
      key: `${role}-${seg.id}`,
      role,
      text: seg.text,
      isFinal: seg.final,
      time: seg.firstReceivedTime,
    });
  }
  return msgs;
}

function TranscriptPanel() {
  const { audioTrack } = useVoiceAssistant();
  const room = useRoomContext();

  // Agent transcription — from agent's published audio track
  const { segments: agentSegments } = useTrackTranscription(audioTrack);

  const [rawUserMsgs, setRawUserMsgs] = useState<DisplayMessage[]>([]);

  useEffect(() => {
    if (!room) return;
    
    const onTranscription = (segments: any[], participant?: any, publication?: any) => {
      // Just log everything to debug
      console.log("[TRANSCRIPTION]", { segments, participant: participant?.identity, pub: publication?.source });
      
      // If it's not the agent, assume it's the user
      if (participant && !participant.isAgent) {
        setRawUserMsgs(prev => {
          const newMsgs = [...prev];
          for (const seg of segments) {
            const existingIdx = newMsgs.findIndex(m => m.key === `user-${seg.id}`);
            const msg: DisplayMessage = {
              key: `user-${seg.id}`,
              role: "user",
              text: seg.text,
              isFinal: seg.final,
              time: seg.firstReceivedTime,
            };
            
            if (existingIdx >= 0) {
              newMsgs[existingIdx] = msg;
            } else {
              newMsgs.push(msg);
            }
          }
          return newMsgs;
        });
      }
    };

    room.on(RoomEvent.TranscriptionReceived, onTranscription);
    return () => {
      room.off(RoomEvent.TranscriptionReceived, onTranscription);
    };
  }, [room]);

  // Merge and sort chronologically
  const messages = useMemo(() => {
    const agentMsgs = segmentsToMessages(agentSegments, "agent");
    return [...agentMsgs, ...rawUserMsgs].sort((a, b) => a.time - b.time);
  }, [agentSegments, rawUserMsgs]);

  // Auto-scroll
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  return (
    <div className="transcript-panel">
      <div className="transcript-header">
        <span className="transcript-dot" />
        Transcript
      </div>
      <div className="transcript-messages" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="transcript-empty">
            Waiting for conversation to begin…
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.key}
              className={`transcript-message ${msg.role}${!msg.isFinal ? " partial" : ""}`}
            >
              <span className="message-label">
                {msg.role === "agent" ? "YieldPoint" : "Operator"}
              </span>
              {msg.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ── Machine Status Bar ────────────────────────────── */
function MachineStatusBar() {
  return (
    <div className="machine-status-bar">
      {MACHINES.map((m) => (
        <div key={m.id} className="machine-chip">
          <span className={`status-dot ${m.status}`} />
          {m.id}
        </div>
      ))}
    </div>
  );
}
