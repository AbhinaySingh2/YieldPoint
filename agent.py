"""
YieldPoint - Hands-Free Floor Technician Backend
Runs the LiveKit WebRTC agent with Deepgram STT, Groq Qwen LLM, and Rime TTS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated

from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    TurnHandlingOptions,
    function_tool,
    get_job_context,
)

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
        "next_service":   "2026-09-01",           # overdue!
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
        "status":         "offline - undergoing scheduled maintenance",
    },
}

# In-memory maintenance log (simulates persistent store)
MAINTENANCE_LOG: list[dict] = []


# These are plain async functions decorated with @function_tool.
# The AgentSession passes them to the LLM; the LLM decides when to call.

@function_tool()
async def check_spindle_tolerance(
    context: RunContext,
    machine_id: Annotated[str, "The machine identifier, e.g. CNC-4401"],
) -> str:
    """
    Look up the current spindle tolerance and service schedule
    for a given CNC machine.  Returns a concise JSON payload.
    """
    logger.info("[TOOL] check_spindle_tolerance(%s)", machine_id)

    record = MACHINE_DB.get(machine_id.upper())
    if record is None:
        return json.dumps({"error": f"Machine '{machine_id}' not found in database."})

    return json.dumps(record, indent=2)


@function_tool()
async def check_press_pressure(
    context: RunContext,
    machine_id: Annotated[str, "The press identifier, e.g. PRESS-801"],
) -> str:
    """
    Look up the current hydraulic pressure and rated tolerance
    for a stamping press.
    """
    logger.info("[TOOL] check_press_pressure(%s)", machine_id)

    record = MACHINE_DB.get(machine_id.upper())
    if record is None:
        return json.dumps({"error": f"Press '{machine_id}' not found in database."})

    return json.dumps(record, indent=2)


@function_tool()
async def log_maintenance_event(
    context: RunContext,
    machine_id: Annotated[str, "The machine identifier"],
    event_type: Annotated[str, "Type of event: inspection | repair | anomaly | pressure_drop | tolerance_drift"],
    description: Annotated[str, "Short plain-text description of the event"],
) -> str:
    """
    Log a predictive-maintenance event against a machine.
    Operators use this to record anomalies, inspections, or
    unexpected readings hands-free.
    """
    logger.info("[TOOL] log_maintenance_event(%s, %s)", machine_id, event_type)

    entry = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "machine_id":  machine_id.upper(),
        "event_type":  event_type,
        "description": description,
    }
    MAINTENANCE_LOG.append(entry)

    return json.dumps({
        "status":  "logged",
        "entry":   entry,
        "total_entries": len(MAINTENANCE_LOG),
    }, indent=2)


@function_tool()
async def list_maintenance_log(
    context: RunContext,
    machine_id: Annotated[str | None, "Optional machine ID filter"] = None,
) -> str:
    """
    Retrieve the recent maintenance log, optionally filtered by machine.
    """
    logger.info("[TOOL] list_maintenance_log(machine_id=%s)", machine_id)

    entries = MAINTENANCE_LOG
    if machine_id:
        entries = [e for e in entries if e["machine_id"] == machine_id.upper()]

    if not entries:
        return json.dumps({"message": "No maintenance entries found."})

    return json.dumps(entries[-10:], indent=2)  # last 10



SYSTEM_PROMPT = """\
You are YieldPoint, a voice assistant for floor-technicians.
Speak extremely fast, concisely, and practically.
NO MARKDOWN (no asterisks, bold, hashes). Say units ("five mm").
If interrupted, answer the new query immediately.
Keep it under 15 words. Lead with verdicts (nominal/warning/critical).
"""


class FloorTechAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[
                check_spindle_tolerance,
                check_press_pressure,
                log_maintenance_event,
                list_maintenance_log,
            ],
        )

async def entrypoint(ctx: JobContext) -> None:
    logger.info("Connecting to LiveKit room...")
    if hasattr(ctx, "job"):
        ctx.job.enable_recording = False
    await ctx.connect()

    participant = await ctx.wait_for_participant()
    logger.info("Operator joined: %s", participant.identity)

    stt_plugin = deepgram.STT(model="nova-2")
    llm_plugin = openai.LLM(
        model="openai/gpt-oss-20b",
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ.get("GROQ_API_KEY"),
    )
    tts_plugin = rime.TTS(
        model="coda",
        speaker="celeste",
        reduce_latency=True,
    )
    
    # Ultra-aggressive VAD settings
    vad_plugin = silero.VAD.load(
        activation_threshold=0.75,
        min_silence_duration=0.25,  # Super fast turn handoff
    )

    turn_options = TurnHandlingOptions(
        endpointing={"min_delay": 0.1, "max_delay": 0.2},
        preemptive_generation={"enabled": True, "preemptive_tts": True},
        # Disable adaptive interruption to prevent network timeouts (408)
        interruption={"enabled": True, "detector": None},
    )

    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad_plugin,
        turn_handling=turn_options,
    )

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
        text = getattr(ev, 'transcript', getattr(ev, 'text', str(ev)))
        is_final = getattr(ev, 'is_final', getattr(ev, 'final', False))
        logger.info('[STT] final=%s %s', is_final, text)
        seg_id = getattr(ev, 'item_id', None) or getattr(ev, 'id', None) or str(uuid.uuid4())
        segment = rtc.TranscriptionSegment(
            id=seg_id,
            text=text,
            start_time=0,
            end_time=0,
            language=getattr(ev, 'language', 'en') or 'en',
            final=bool(is_final),
        )
        # Find participant's mic track SID
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
        "STT: Deepgram Nova-2 | "
        "LLM: Groq GPT-OSS 20B | "
        "TTS: Rime Coda / celeste | "
        "Turn: Adaptive interruption detection"
    )

    await session.start(
        room=ctx.room,
        agent=agent,
    )



    await session.generate_reply(
        instructions=(
            "Greet the operator briefly.  Say: "
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
