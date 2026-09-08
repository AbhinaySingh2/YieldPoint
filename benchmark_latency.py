"""
YieldPoint benchmark: perceived response time + turn-handling correctness.

This does NOT hook into livekit-agents internals (we got burned guessing at
those earlier in this project). Instead it parses the plain-text log that
`agent.py dev` already prints to stdout -- the same log format used
throughout this project's own debugging. That makes it trivially
reproducible: run the agent, redirect stdout to a file, run this script
against that file.

Usage:
    python agent.py dev > run.log 2>&1
    # ... have a conversation, then Ctrl+C ...
    python benchmark_latency.py run.log

What it measures:
  1. Perceived response time: wall-clock time from the "user turn
     committed" debug line to the next "[TIMING] TTS time-to-first-audio-byte"
     line. This is end-to-end: STT finalization + LLM time-to-first-token +
     TTS time-to-first-audio-byte, i.e. what the technician actually
     experiences as "how long before it starts talking."
  2. Turn-handling correctness violations:
       a) any "transcript arrives after turn has been committed" warning
          (the root cause of the garbled-reply bug found in this project)
       b) assistant replies whose text shows the concatenation pattern seen
          in that bug: sentence-ending punctuation immediately followed by
          a capital letter with no space/separator, e.g.
          "...queries.Nominal..." -- a heuristic, not a certainty, so
          flagged occurrences should be spot-checked against the actual
          audio.

Outputs median / p95 perceived response time, and a correctness-violation
count and rate, both to stdout and to a benchmark_results.json file for
inclusion in your submission as reproducible evidence.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

TS_RE = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
USER_TURN_RE = re.compile(TS_RE + r".*user turn committed")
TTS_TTFA_RE = re.compile(TS_RE + r".*\[TIMING\] TTS time-to-first-audio-byte")
LATE_TRANSCRIPT_RE = re.compile(
    r"transcript arrives after turn has been committed"
)
ASSISTANT_ITEM_RE = re.compile(
    r'"role":\s*"assistant".*?"lk\.pii\.text":\s*"([^"]*)"'
)
# Heuristic for the concatenation bug: sentence-ending punctuation directly
# followed by a capital letter, no space in between.
CONCAT_HEURISTIC_RE = re.compile(r"[.?!][A-Z]")

TS_FMT = "%Y-%m-%d %H:%M:%S,%f"


@dataclass
class TurnLatency:
    user_turn_committed_at: str
    tts_first_audio_at: str
    perceived_response_time_s: float


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, TS_FMT)


def main(log_path: str) -> None:
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    turn_times: list[datetime] = []
    latencies: list[TurnLatency] = []
    late_transcript_count = 0
    concat_flagged: list[str] = []
    assistant_reply_count = 0

    pending_turn_ts: datetime | None = None

    for line in lines:
        if LATE_TRANSCRIPT_RE.search(line):
            late_transcript_count += 1
            continue

        m = USER_TURN_RE.search(line)
        if m:
            pending_turn_ts = parse_ts(m.group(1))
            continue

        m = TTS_TTFA_RE.search(line)
        if m and pending_turn_ts is not None:
            audio_ts = parse_ts(m.group(1))
            delta = (audio_ts - pending_turn_ts).total_seconds()
            if 0 <= delta < 30:  # sanity bound; discard obvious mismatches
                latencies.append(
                    TurnLatency(
                        user_turn_committed_at=pending_turn_ts.strftime(TS_FMT)[:-3],
                        tts_first_audio_at=audio_ts.strftime(TS_FMT)[:-3],
                        perceived_response_time_s=round(delta, 3),
                    )
                )
            pending_turn_ts = None
            continue

        for text_match in ASSISTANT_ITEM_RE.finditer(line):
            assistant_reply_count += 1
            text = text_match.group(1)
            if CONCAT_HEURISTIC_RE.search(text):
                concat_flagged.append(text)

    samples = [t.perceived_response_time_s for t in latencies]

    result = {
        "log_file": log_path,
        "perceived_response_time": {
            "n_samples": len(samples),
            "median_s": round(statistics.median(samples), 3) if samples else None,
            "p95_s": (
                round(statistics.quantiles(samples, n=20)[18], 3)
                if len(samples) >= 5
                else None
            ),
            "min_s": round(min(samples), 3) if samples else None,
            "max_s": round(max(samples), 3) if samples else None,
            "note": (
                "First sample in a session includes worker/model warmup and "
                "is a cold run; treat separately from steady-state (warm) "
                "samples per the hackathon's cached-vs-uncached guidance."
            ),
            "samples": [asdict(t) for t in latencies],
        },
        "turn_handling_correctness": {
            "assistant_replies_total": assistant_reply_count,
            "late_transcript_warnings": late_transcript_count,
            "concatenation_heuristic_flags": len(concat_flagged),
            "concatenation_flag_rate": (
                round(len(concat_flagged) / assistant_reply_count, 3)
                if assistant_reply_count
                else None
            ),
            "flagged_examples": concat_flagged,
            "note": (
                "A violation is either a late-transcript warning or a "
                "flagged concatenated reply. The heuristic can false-flag "
                "legitimate abbreviations; spot-check flagged_examples "
                "against the actual audio before citing a rate."
            ),
        },
    }

    print(json.dumps(result, indent=2))
    with open("benchmark_results.json", "w", encoding="utf-8") as out:
        json.dump(result, out, indent=2)
    print(f"\nWrote benchmark_results.json ({len(samples)} latency samples, "
          f"{late_transcript_count} late-transcript warnings, "
          f"{len(concat_flagged)} concatenation flags)", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python benchmark_latency.py <log_file>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
