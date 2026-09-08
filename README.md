# YieldPoint

A hands-free voice agent for shop-floor technicians. Ask it about machine
status (CNC spindle tolerance, hydraulic press pressure) and log maintenance
events, entirely by voice -- no screen, no keyboard, gloves stay on.

Built for the DataForge x Pathway x Rime hackathon. Rime provides all
spoken output; see [RIME_EVIDENCE.md](./RIME_EVIDENCE.md) for the hard
voice problem this project targets and how it's measured.

## Architecture

```
Operator mic  --STT-->  Deepgram (nova-3)
                            |
                       LiveKit Agents (turn handling, tool orchestration)
                            |
                          LLM  -->  Groq (qwen/qwen3.8-27b)
                            |
                          TTS  -->  Rime (coda / cove)  --> Operator speaker
```

- **Transport / orchestration**: LiveKit Agents (`livekit-agents` 1.8.0),
  connected to a LiveKit Cloud room.
- **STT**: Deepgram `nova-3`, with a domain keyterm list (`spindle`,
  `tolerance`, machine IDs, etc.) to improve recognition of shop-floor
  vocabulary.
- **LLM**: `qwen/qwen3.8-27b` served through Groq's OpenAI-compatible
  endpoint (`https://api.groq.com/openai/v1`).
- **TTS**: Rime, model `mistv3` (env-overridable via `RIME_MODEL`, e.g. set
  to `coda` to A/B against the flagship model), speaker `cove`. Swapped
  from Coda to Mist v3 specifically to hit a sub-1000ms perceived-response-
  time target -- see [RIME_EVIDENCE.md](./RIME_EVIDENCE.md) for the
  measured trade-off against Coda's higher quality.- **VAD**: Silero.
- **Turn handling**: `TurnHandlingOptions` with `endpointing.min_delay=0.5s`
  / `max_delay=0.8s`, preemptive generation enabled. See
  [RIME_EVIDENCE.md](./RIME_EVIDENCE.md) for why `min_delay` is 0.5s and
  not the library default of 0.1s.

## Setup

```
pip install -r requirements.txt
cp .env.example .env
# fill in .env with real credentials -- never commit .env itself
python agent.py dev
```

Required environment variables (see `.env.example`):

| Variable | Used for |
|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | LiveKit room connection |
| `DEEPGRAM_API_KEY` | Speech-to-text |
| `GROQ_API_KEY` | LLM inference |
| `RIME_API_KEY` | Text-to-speech (primary spoken output) |

## Third-party services

- LiveKit Cloud (room/transport)
- Deepgram (STT)
- Groq (LLM hosting)
- Rime (TTS -- primary spoken output for this project)

## Known limitations

- TTS synthesis time (Rime `coda`) is the dominant remaining latency cost,
  roughly 2.5-3.5s for short replies in development testing. `coda` is
  tuned for voice quality over minimum latency; see RIME_EVIDENCE.md for
  the tradeoff against faster Rime models.
- No fallback TTS/STT/LLM provider is configured. If Groq, Deepgram, or
  Rime is unreachable, the relevant pipeline stage will raise rather than
  degrade gracefully. Per the hackathon's fallback-disclosure rule: **there
  is no fallback path in this submission** -- Rime is the only speech
  provider used, always.
- The adaptive interruption detector (LiveKit Cloud) can time out (~0.7s)
  under load and fall back to VAD-based interruption; this is graceful
  degradation, not a crash, but interruption precision can vary between
  turns as a result.
- STT accuracy on heavy background/shop noise beyond what was tested here
  is unverified; the keyterm list improves recognition of domain
  vocabulary but doesn't eliminate mishears entirely.
- `MACHINE_DB` and `MAINTENANCE_LOG` are in-memory, synthetic fixture data
  for the demo -- no real machine telemetry or persistent storage.

## Failure behavior

- Unknown machine ID -> tool returns a JSON `{"error": ...}` payload, which
  the LLM is expected to relay back to the technician in the "under 15
  words, no markdown" house style rather than crashing.
- STT/LLM/TTS API errors currently propagate as exceptions (see "no
  fallback" above) -- not yet caught and converted into a spoken "system
  unavailable" message. This is the clearest next-step improvement.

## Exact Rime configuration

- Model: `mistv3` (set `RIME_MODEL=coda` to run the flagship model instead)
- Speaker: `cove`
- Language: `en`
- Audio format / sample rate / transport: Managed automatically by LiveKit Agents.
- Endpoint / region: default