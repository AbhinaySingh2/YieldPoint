# YieldPoint
**A Rime Hackathon Submission by Team Apex**

YieldPoint is a voice-native intelligent assistant designed for manufacturing production floors. It allows operators and technicians to check machine specifications, retrieve maintenance schedules, and log safety/maintenance events entirely hands-free.

## Voice Native Design
A simple chatbot with a play button does not work on a noisy production floor where operators wear gloves and have their hands full of tools. Voice is absolutely essential to this experience. 

### The Hard Voice Problem: Perceived Response Time
We focused on reducing **Perceived Response Time**. By tuning Voice Activity Detection endpointing (`min_delay: 0.2`) and enabling **Preemptive TTS Generation** (speculative synthesis), we successfully masked TTS latency and brought the glass-to-glass response time down to human-conversational levels (< 500ms). See `RIME_EVIDENCE.md` for full acceptance criteria.

---

## Technical Architecture

The project is split into a robust Python backend agent and a sleek Next.js WebRTC frontend.

- **Backend (Python)**: Uses the LiveKit Agents SDK. The agent is built on `AgentSession` and orchestrates STT, LLM function calling, and TTS generation.
- **Frontend (Next.js)**: A React application utilizing `@livekit/components-react` to handle secure token generation, microphone access, and WebRTC streaming directly to the backend.

### Third-Party Services
- **Voice Orchestration & Transport**: LiveKit (WebRTC)
- **Speech-to-Text (STT)**: Deepgram (`nova-2`)
- **Language Model (LLM)**: Google Gemini (`gemini-3.5-flash-lite`)
- **Text-to-Speech (TTS)**: Rime

### Rime Integration Details
- **Model ID**: `coda`
- **Speaker**: `celeste`
- **Language**: English (`en-US`)
- **Endpoint**: LiveKit native Rime integration proxy
- **Audio Format**: PCM 24kHz (negotiated dynamically by WebRTC)
- **Transport**: WebRTC (LiveKit)

---

## Setup Instructions

### 1. Configuration Hygiene
Copy the `.env.example` file to create your local `.env` files.
```bash
cp .env.example .env
cp .env.example frontend/.env.local
```
Fill in the placeholders with your actual LiveKit, Deepgram, Gemini, and Rime API keys. **Never commit live credentials.**

### 2. Run the Backend Agent
Ensure you have Python 3.12+ installed.
```bash
pip install -r requirements.txt
python agent.py dev
```

### 3. Run the Frontend UI
In a separate terminal, start the Next.js server.
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:3000` in your browser and click "Connect to Agent" to begin speaking.

---

## Known Limitations & Failure Behavior
- **Interruptions**: If the user aggressively interrupts the agent mid-sentence, the agent will instantly cancel the current action and flush the Rime audio buffer. Stale tool calls might still execute if the LLM already triggered them before the interruption was processed.
- **Noisy Environments**: Deepgram's `nova-2` model is highly resilient to background noise, but excessive industrial noise may trick the VAD into keeping the turn open longer than the desired 200ms `min_delay`, temporarily increasing latency.
- **Database**: The application currently uses an in-memory mock dictionary (`MACHINE_DB`) for demonstration purposes. If the Python agent restarts, all dynamically logged maintenance events will reset.
