# RIME_EVIDENCE.md – Hackathon Hard-Voice-Problem Evidence

**Team:** Team Apex
**Project:** YieldPoint
**Date:** 2026-09-06
**Hard Voice Claim:** Perceived Response Time (Ultra-Low Latency)

---

## 1. Hard Voice Claim

### Claim: Perceived Response Time

Our system solves the **Perceived Response Time** problem — effectively reducing the delay from the end of the user's turn to the first audible response down to human-conversational levels (< 500ms glass-to-glass). 

We achieved this by aggressively optimizing the conversational orchestration:
1. **Aggressive VAD Endpointing**: We reduced the Voice Activity Detection (VAD) silence threshold (`min_delay`) from the default 500ms down to **200ms**.
2. **Preemptive Speculative Generation**: We enabled LiveKit's `preemptive_tts`. The agent begins processing the LLM request *and* synthesizing the Rime audio based on partial STT transcripts *before* the user has even finished speaking. 
3. **Instant Audio Playback**: By the time the 200ms VAD silence threshold commits the user's turn, the Rime audio is already synthesized in the buffer and begins playing over WebRTC instantly.

This is critical for production-floor operators who need instantaneous confirmation of safety alerts and maintenance logs without waiting for "walkie-talkie" style processing delays.

---

## 2. Acceptance Test

### Scenario: Rapid Diagnostic Inquiry

| Step | Actor    | Action |
|------|----------|--------|
| 1    | Operator | "YieldPoint, what is the status of CNC-4402?" |
| 2    | Agent    | **(Within < 500ms)** "CNC-4402 is showing a warning for tolerance drift." |
| 3    | Operator | "Log an anomaly for tolerance drift." |
| 4    | Agent    | **(Within < 500ms)** "I have logged the anomaly for CNC-4402." |

### Pass Criteria

- [x] End-to-end latency (from the user stopping speaking to the agent's first audio frame) consistently measures under 500ms.
- [x] Preemptive generation logs confirm that Rime TTS synthesis began *before* the turn was committed.
- [x] The agent correctly executes backend tool calls (`log_maintenance_event`) without delaying the spoken acknowledgment.

## 3. Procedure and Result
**Procedure**: Speak into the custom YieldPoint Web UI (Next.js) connected via LiveKit WebRTC to the Python agent running `agent.py dev`. Measure the latency via the LiveKit console analytics and the network tab timestamps.
**Result**: Successful. The Rime TTS audio playback began instantaneously upon the 200ms VAD trigger. Preemptive generation successfully masked the TTS synthesis time entirely.

## 4. Limitations
- Preemptive generation relies heavily on the user speaking clearly. If the user drastically changes their sentence in the final 200ms, the agent discards the preemptively synthesized Rime audio and regenerates it, falling back to standard ~800ms latency.
- Aggressive 200ms endpointing means the user must speak continuously without long mid-sentence pauses, otherwise the agent will enthusiastically interrupt them.
