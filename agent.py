"""
YieldPoint - Hands-Free Floor Technician Backend
Optimized for Sub-500ms Latency & Instant Interruption Recovery
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncIterable

from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    ModelSettings,
    RunContext,
    TurnHandlingOptions,
    function_tool,
)
from livekit.agents.llm import ChatChunk, ChatContext, ChatMessage

from livekit.plugins import deepgram, rime, silero, openai

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-28s  %(levelname)s  %(message)s")
logger = logging.getLogger("floor_tech_agent")

MACHINE_DB: dict[str, dict] = {
    "CNC-4401": {
        "machine":        "CNC-4401  (Haas VF-4SS)",
        "spindle_rpm":    12_000,
        "tolerance_mm":   0.005,
        "last_service":   "2026-08-22",
        "next_service":   "2026-09-15",
        "spindle_hours":  1_872,
        "status":         "nominal",
    },
    "CNC-4402": {
        "machine":        "CNC-4402  (Haas VF-4SS)",
        "spindle_rpm":    12_000,
        "tolerance_mm":   0.012,
        "last_service":   "2026-07-10",
        "next_service":   "2026-09-01",
        "spindle_hours":  3_410,
        "status":         "warning - tolerance drift detected",
    },
    "PRESS-801": {
        "machine":        "PRESS-801  (Schuler 800-ton)",
        "rated_pressure_bar": 250,
        "current_pressure_bar": 247,
        "tolerance_bar":  5,
        "last_service":   "2026-08-01",
        "next_service":   "2026-10-01",
        "status":         "nominal",
    },
    "PRESS-802": {
        "machine":        "PRESS-802  (Schuler 800-ton)",
        "rated_pressure_bar": 250,
        "current_pressure_bar": 210,
        "tolerance_bar":  5,
        "last_service":   "2026-05-15",
        "next_service":   "2026-08-15",
        "status":         "critical - pressure drop detected",
    },
    "CNC-4403": {
        "machine":        "CNC-4403  (Mazak Integrex)",
        "spindle_rpm":    10_000,
        "tolerance_mm":   0.003,
        "last_service":   "2026-09-01",
        "next_service":   "2026-12-01",
        "spindle_hours":  520,
        "status":         "offline - scheduled maintenance",
    },
}

MAINTENANCE_LOG: list[dict] = []

# Vocabulary the floor is actually going to say out loud. Feeding this to
# Deepgram as keyterms materially improves recognition of machine IDs and
# domain jargon over noisy shop-floor audio -- this is what was turning
# "What can you do now" into "Watch Deepgram now" and dropping words
# entirely on other turns.
DOMAIN_KEYTERMS = [
    "spindle", "tolerance", "press", "hydraulic", "pressure",
    "CNC-4401", "CNC-4402", "CNC-4403", "PRESS-801", "PRESS-802",
    "maintenance", "calibration", "drift",
]


@function_tool()
async def check_spindle_tolerance(
    context: RunContext,
    machine_id: Annotated[str, "The machine identifier, e.g. CNC-4401"],
) -> str:
    """Look up current spindle tolerance for a CNC machine."""
    logger.info("[TOOL] check_spindle_tolerance(%s)", machine_id)
    record = MACHINE_DB.get(machine_id.upper().replace(" ", "-"))
    if record is None:
        return json.dumps({"error": f"'{machine_id}' not found."})
    return json.dumps({
        "machine": record["machine"],
        "tolerance_mm": record["tolerance_mm"],
        "status": record["status"],
    })


@function_tool()
async def check_press_pressure(
    context: RunContext,
    machine_id: Annotated[str, "The press identifier, e.g. PRESS-801"],
) -> str:
    """Look up current hydraulic pressure and rated tolerance for a press."""
    logger.info("[TOOL] check_press_pressure(%s)", machine_id)
    record = MACHINE_DB.get(machine_id.upper().replace(" ", "-"))
    if record is None:
        return json.dumps({"error": f"'{machine_id}' not found."})
    return json.dumps({
        "machine": record["machine"],
        "current_pressure_bar": record["current_pressure_bar"],
        "status": record["status"],
    })


@function_tool()
async def log_maintenance_event(
    context: RunContext,
    machine_id: Annotated[str, "The machine identifier"],
    event_type: Annotated[str, "Type of event: inspection | repair | anomaly | pressure_drop | tolerance_drift"],
    description: Annotated[str, "Short plain-text description of the event"],
) -> str:
    """Log a predictive-maintenance event hands-free."""
    logger.info("[TOOL] log_maintenance_event(%s, %s)", machine_id, event_type)
    entry = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "machine_id":  machine_id.upper().replace(" ", "-"),
        "event_type":  event_type,
        "description": description,
    }
    MAINTENANCE_LOG.append(entry)
    return json.dumps({"status": "logged", "total_entries": len(MAINTENANCE_LOG)})


@function_tool()
async def list_maintenance_log(
    context: RunContext,
    machine_id: Annotated[str | None, "Optional machine ID filter"] = None,
) -> str:
    """Retrieve the recent maintenance log."""
    logger.info("[TOOL] list_maintenance_log(machine_id=%s)", machine_id)
    entries = MAINTENANCE_LOG
    if machine_id:
        clean_id = machine_id.upper().replace(" ", "-")
        entries = [e for e in entries if e["machine_id"] == clean_id]
    if not entries:
        return json.dumps({"message": "No entries found."})
    return json.dumps(entries[-5:])


SYSTEM_PROMPT = """\
You are YieldPoint, a voice assistant for floor-technicians.
Speak extremely fast, concisely, and practically.
NO MARKDOWN (no asterisks, bold, hashes). Say units ("five mm").
If interrupted, answer the new query immediately.
Keep it under 15 words. Lead with verdicts (nominal/warning/critical).
NEVER include internal notes, reasoning, or trailing monologues (e.g. "Note: we should stop here"). End your response immediately.
"""


class FloorTechAgent(Agent):
    def __init__(self) -> None:
        # Seed the chat context on the Agent itself, via the public
        # `chat_ctx` param, BEFORE the session starts. Qwen's chat template
        # requires at least one role="user" message to render at all --
        # without this, the first-turn request 400s with
        # "No user query found in messages."
        initial_ctx = ChatContext()
        initial_ctx.add_message(
            role="user",
            content="Hello, terminal. Are you online?",
        )
        super().__init__(
            instructions=SYSTEM_PROMPT,
            chat_ctx=initial_ctx,
            tools=[
                check_spindle_tolerance,
                check_press_pressure,
                log_maintenance_event,
                list_maintenance_log,
            ],
        )

    # --- Latency instrumentation -------------------------------------
    #
    # These override the default node behavior purely to log timing;
    # they don't change what gets generated. This is what tells us
    # whether a slow turn is the LLM or the TTS -- previously the log
    # only showed when the full item was committed, so a 5-8s turn was
    # a black box.
    #
    # NOTE: `Agent.default.llm_node` / `Agent.default.tts_node` are the
    # documented hooks for delegating to default behavior while wrapping
    # it (LiveKit Agents' "node customization" pattern). Signatures can
    # shift between livekit-agents releases -- if this errors on import,
    # check `python -c "import livekit.agents; help(livekit.agents.Agent)"`
    # against your installed version and adjust the parameters below.

    async def llm_node(
        self, chat_ctx: ChatContext, tools: list, model_settings: ModelSettings
    ) -> AsyncIterable[ChatChunk]:
        start = time.monotonic()
        first_token_seen = False
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if not first_token_seen:
                first_token_seen = True
                logger.info("[TIMING] LLM time-to-first-token: %.3fs", time.monotonic() - start)
            yield chunk
        logger.info("[TIMING] LLM total generation time: %.3fs", time.monotonic() - start)

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        start = time.monotonic()
        first_audio_seen = False
        async for frame in Agent.default.tts_node(self, text, model_settings):
            if not first_audio_seen:
                first_audio_seen = True
                logger.info("[TIMING] TTS time-to-first-audio-byte: %.3fs", time.monotonic() - start)
            yield frame
        logger.info("[TIMING] TTS total synthesis time: %.3fs", time.monotonic() - start)


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Connecting to LiveKit room...")
    await ctx.connect()

    participant = await ctx.wait_for_participant()
    logger.info("Operator joined: %s", participant.identity)

    # nova-3 over nova-2: materially better on noisy/industrial audio,
    # plus keyterm boosting for the shop-floor vocabulary that was
    # getting mangled (machine IDs, "spindle", "tolerance", etc).
    stt_plugin = deepgram.STT(
        model="nova-3",
        keyterms=DOMAIN_KEYTERMS,
    )

    # Reverting to qwen/qwen3.8-27b: The model IS available on Groq and avoids
    # the hallucinated repetition seen in gpt-oss-120b. It also provides much 
    # faster generation (~600ms vs ~2.6s), crucial for the sub-500ms TTFB target.
    llm_plugin = openai.LLM(
        model="qwen/qwen3.8-27b",
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ.get("GROQ_API_KEY"),
    )

    # Coda -> Mist v3 for the sub-1000ms perceived-response-time target.
    # Per Rime's own docs (docs.rime.ai/docs/models): modelId "mistv3" has
    # typical TTFB "well below 100ms," vs Coda's sub-100ms *model* latency
    # that in our own measurements still produced 0.4-1.3s real-world
    # time-to-first-audio-byte once network/queueing is included.
    # Note: 'celeste' is not available on Mist v3 despite prior docs, so using 'cove'.
    # Trade-off: Mist is rated below Coda/Arcana on
    # expressiveness in Rime's own comparisons -- reasonable for a terse
    # "verdict-first" machine-status readout, but worth confirming by ear.
    #
    # Kept env-overridable so both configs can be A/B'd with
    # benchmark_latency.py without a code change -- run once with each,
    # compare benchmark_results.json, and cite both in RIME_EVIDENCE.md
    # rather than asserting the swap helped without measuring it.
    tts_plugin = rime.TTS(
        model=os.environ.get("RIME_MODEL", "mistv3"),
        speaker="cove",
    )

    # Fast interruption threshold
    vad_plugin = silero.VAD.load(
        activation_threshold=0.5,
        min_silence_duration=0.25,
    )

    turn_options = TurnHandlingOptions(
        # min_delay raised from 0.1 -> 0.5: the log's own warning
        # ("transcript arrives after turn has been committed") showed
        # turns committing before Deepgram finished finalizing, which
        # let a stale reply and a new one get concatenated into one
        # garbled TTS utterance. 0.5s gives STT enough headroom while
        # still being well under a second.
        endpointing={"min_delay": 0.5, "max_delay": 0.8},
        preemptive_generation={"enabled": True, "preemptive_tts": True},
        # "detector": None was removed -- InterruptionOptions.__annotations__
        # (confirmed via help(livekit.agents.voice.turn)) has no "detector"
        # key at all. TypedDicts don't validate at runtime, so it was being
        # silently accepted and doing nothing since it was first added.
        interruption={"enabled": True},
    )

    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad_plugin,
        turn_handling=turn_options,
    )

    # NOTE: an earlier version of this file also tried to log per-turn
    # round-trip time via session.on("user_turn_committed"/"agent_speech_committed").
    # Those event names were a guess and never fired -- your 1.8.0 install
    # doesn't emit them (or emits them under different names). The
    # llm_node/tts_node timing above already answers the latency question,
    # so that dead code is removed rather than left guessing a third time.
    # If you want ground-truth event names instead of another guess from
    # me, run:
    #   python -c "import livekit.agents, os; print(os.path.dirname(livekit.agents.__file__))"
    # then grep that directory's voice/*.py for `.emit(` to see the exact
    # strings AgentSession actually emits, and I'll wire it up precisely.

    @session.on("agent_speech_interrupted")
    def _on_interrupted(ev) -> None:
        logger.warning(
            "[INTERRUPTED] "
            "Rime TTS buffer flushed, generation cancelled. "
            "Context trimmed to last-heard boundary."
        )

    @session.on("agent_speech_completed")
    def _on_completed(ev) -> None:
        logger.info("[SPEECH DONE] Agent speech completed (no interruption).")

    @session.on("user_input_transcribed")
    def _on_transcription(ev) -> None:
        text = getattr(ev, "transcript", getattr(ev, "text", str(ev)))
        is_final = getattr(ev, "is_final", getattr(ev, "final", False))
        logger.info("[STT] final=%s %s", is_final, text)
        seg_id = getattr(ev, "item_id", None) or getattr(ev, "id", None) or str(uuid.uuid4())
        segment = rtc.TranscriptionSegment(
            id=seg_id,
            text=text,
            start_time=0,
            end_time=0,
            language=getattr(ev, "language", "en") or "en",
            final=bool(is_final),
        )
        track_sid = ""
        for pub in participant.track_publications.values():
            if pub.source == rtc.TrackSource.SOURCE_MICROPHONE:
                track_sid = pub.sid
                break
        t = rtc.Transcription(
            participant_identity=participant.identity,
            track_sid=track_sid,
            segments=[segment],
        )
        asyncio.ensure_future(ctx.room.local_participant.publish_transcription(t))

    @session.on("function_calls_started")
    def _on_tool_start(ev) -> None:
        logger.info("[TOOL START] Tool execution started.")

    @session.on("function_calls_finished")
    def _on_tool_done(ev) -> None:
        logger.info("[TOOL DONE] Tool execution completed.")

    agent = FloorTechAgent()

    logger.info(
        "Starting YieldPoint Agent -- "
        "STT: Deepgram Nova-3 | "
        "LLM: Groq qwen/qwen3.8-27b | "
        "TTS: Rime Mist v3 / cove"
    )

    # Agent already carries the seeded user turn (see FloorTechAgent.__init__),
    # so no private/internal context poking is needed here.
    await session.start(
        room=ctx.room,
        agent=agent,
    )

    await session.generate_reply(
        instructions=(
            "Greet the operator briefly. Say: "
            "'YieldPoint online. Ready for maintenance checks or logging. "
            "What do you need?'"
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            agent_name="floor-tech-local",
            entrypoint_fnc=entrypoint,
        ),
    )