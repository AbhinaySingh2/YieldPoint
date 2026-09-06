"use client";

import { useState, useCallback } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  BarVisualizer,
  useVoiceAssistant,
} from "@livekit/components-react";

export default function Home() {
  const [token, setToken] = useState<string>("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string>("");

  const connectToAgent = useCallback(async () => {
    try {
      setIsConnecting(true);
      setError("");
      
      const response = await fetch("/api/token?room=floor-tech-local");
      if (!response.ok) {
        throw new Error("Failed to fetch token");
      }
      
      const data = await response.json();
      if (data.error) {
        throw new Error(data.error);
      }
      
      setToken(data.token);
    } catch (e: any) {
      setError(e.message || "Connection failed");
      console.error(e);
    } finally {
      setIsConnecting(false);
    }
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
          <p style={{ marginBottom: "2rem", color: "#a0aec0" }}>
            Click below to establish a secure voice connection with the maintenance registry.
          </p>
          <button 
            className="connect-btn" 
            onClick={connectToAgent}
            disabled={isConnecting}
          >
            {isConnecting ? "Connecting..." : "Connect to Agent"}
          </button>
          {error && <p style={{ color: "#ff4d4d", marginTop: "1rem" }}>{error}</p>}
        </div>
      ) : (
        <LiveKitRoom
          token={token}
          serverUrl={process.env.NEXT_PUBLIC_LIVEKIT_URL}
          connect={true}
          audio={true}
          video={false}
          onDisconnected={() => setToken("")}
          className="active-room"
        >
          <RoomAudioRenderer />
          
          <div className="visualizer-container">
            <AgentVisualizer />
          </div>

          <VoiceAssistantControlBar />
        </LiveKitRoom>
      )}
    </main>
  );
}

// Separate component for the visualizer to use the useVoiceAssistant hook
function AgentVisualizer() {
  const { state, audioTrack } = useVoiceAssistant();
  
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "1rem" }}>
      <BarVisualizer
        state={state}
        barCount={5}
        trackRef={audioTrack}
        options={{ minHeight: 24 }}
        style={{ height: "150px" }}
      />
      <div style={{ color: "#00e5ff", fontWeight: 600, letterSpacing: "2px", textTransform: "uppercase", fontSize: "0.8rem" }}>
        {state === "speaking" ? "Agent Speaking" : state === "listening" ? "Agent Listening" : "Agent Idle"}
      </div>
    </div>
  );
}
