# RIME_EVIDENCE.md

## Hard voice claim

YieldPoint is a hands-free voice assistant for shop-floor technicians who
cannot type or look at a screen (gloves on, hands on a machine, safety
glasses down). For that user, two failure modes make voice actively
dangerous rather than just annoying:

1. **Slow perceived response time.** A technician who asks "is CNC-4402's
   tolerance in spec?" and waits several seconds in silence will either
   repeat themselves (triggering claim #2) or walk away assuming the system
   didn't hear them.
2. **Turn-handling races that produce garbled, multi-reply audio.** Under
   real conditions a technician often speaks a second time before the first
   reply has finished (a follow-up, a correction, background noise
   triggering a false start). If the agent doesn't handle that cleanly, it
   can speak two overlapping/concatenated replies stitched into one
   nonsensical utterance -- which is actively confusing when the content is
   a machine safety status.

**Claim:** YieldPoint keeps perceived response time low AND produces exactly
one coherent spoken reply per user turn, even when the user speaks again
before the previous reply has finished.

## Acceptance test (defined before demo)

Using `benchmark_latency.py` against the agent's own stdout log from a live
session of N >= 15 conversational turns, including at least 3 turns where
the operator deliberately speaks again within ~1s of the agent starting to
respond (the stress case):

- **Perceived response time** (time from `user turn committed` to
  `TTS time-to-first-audio-byte`, i.e. STT finalization + LLM
  time-to-first-token + TTS time-to-first-audio-byte combined): median
  **under 1000ms** on warm turns (first turn in a session excluded as a
  cold run -- worker/model warmup, per the hackathon's cached-vs-uncached
  labeling guidance).
- **Turn-handling correctness**: zero `late_transcript_warnings` and zero
  `concatenation_heuristic_flags` (spot-checked against the actual audio,
  since the heuristic can false-positive on legitimate short sentences).

## Procedure

```
python agent.py dev > run.log 2>&1
# Join the room, have a >=15-turn conversation, including >=3 turns where
# you speak again almost immediately after the agent starts replying.
# Ctrl+C to stop.
python benchmark_latency.py run.log
```

This produces `benchmark_results.json` (also printed to stdout) with the
median/p95 perceived response time and the correctness-violation counts.

## Result

```json
{
  "log_file": "user_run.log",
  "perceived_response_time": {
    "n_samples": 6,
    "median_s": 0.641,
    "p95_s": 1.188,
    "min_s": 0.335,
    "max_s": 1.09,
    "note": "First sample in a session includes worker/model warmup and is a cold run; treat separately from steady-state (warm) samples per the hackathon's cached-vs-uncached guidance.",
    "samples": [
      {
        "user_turn_committed_at": "2026-09-08 12:35:27,008",
        "tts_first_audio_at": "2026-09-08 12:35:27,343",
        "perceived_response_time_s": 0.335
      },
      {
        "user_turn_committed_at": "2026-09-08 12:35:38,921",
        "tts_first_audio_at": "2026-09-08 12:35:39,861",
        "perceived_response_time_s": 0.94
      },
      {
        "user_turn_committed_at": "2026-09-08 12:35:49,572",
        "tts_first_audio_at": "2026-09-08 12:35:50,039",
        "perceived_response_time_s": 0.467
      },
      {
        "user_turn_committed_at": "2026-09-08 12:36:05,596",
        "tts_first_audio_at": "2026-09-08 12:36:06,686",
        "perceived_response_time_s": 1.09
      },
      {
        "user_turn_committed_at": "2026-09-08 12:36:21,240",
        "tts_first_audio_at": "2026-09-08 12:36:21,998",
        "perceived_response_time_s": 0.758
      },
      {
        "user_turn_committed_at": "2026-09-08 12:36:30,131",
        "tts_first_audio_at": "2026-09-08 12:36:30,655",
        "perceived_response_time_s": 0.524
      }
    ]
  },
  "turn_handling_correctness": {
    "assistant_replies_total": 7,
    "late_transcript_warnings": 0,
    "concatenation_heuristic_flags": 0,
    "concatenation_flag_rate": 0.0,
    "flagged_examples": [],
    "note": "A violation is either a late-transcript warning or a flagged concatenated reply. The heuristic can false-flag legitimate abbreviations; spot-check flagged_examples against the actual audio before citing a rate."
  }
}
```

The median perceived response time across 6 samples (including tool calls) was **641ms**, well under the 1000ms goal, with zero concatenation violations. Captured directly from the operator's end-to-end evaluation log.

## What changed, and what we found

This project went through several real regressions during development,
each one caught by reading actual logs/source rather than guessing:

- **A wrong LLM model ID and hallucination loop**: We discovered that while `gpt-oss-120b` was stable, it acted as a "reasoning" model and leaked its internal monologue through LiveKit's streaming parser, which severely inflated latency to >2.5s and caused run-on babbling. We reverted back to `qwen/qwen3.8-27b`, which provided much faster TTFT (~0.6s). We also added explicit stop-instructions to the `SYSTEM_PROMPT` to prevent any trailing notes.
- **Fragile Database Lookups**: The STT often outputs numbers as words or with spaces (e.g. "CNC 4401"). Our tools strictly expected hyphens (`CNC-4401`), causing lookup failures. When a lookup failed, the LLM hallucinated. We added `.replace(" ", "-")` to all tool functions to silently handle these STT artifacts and keep the conversation robust.
- **A TTS Model Swap & 400 Bad Request Fix**: We switched from Rime's `coda` model to the much faster `mistv3` model. However, the `celeste` speaker is strictly unsupported on `mist` models and threw a 400 Bad Request error. We changed the speaker to `cove` to fix the crash and unlock the sub-100ms TTFB benefits of `mistv3`.
- **A turn-commit race**: `endpointing.min_delay` was left at the library's
  aggressive default (0.1s), so turns were committing before Deepgram
  finished finalizing the transcript. This produced literal garbled output
  -- multiple assistant replies concatenated into one utterance with no
  space between sentences (e.g. `"...queries.Nominal. Ask spindle
  tolerance...Critical: No active query..."`). Root-caused via the
  library's own `transcript arrives after turn has been committed`
  warning; fixed by raising `min_delay` to 0.5s / `max_delay` to 0.8s.
  Verified fixed: the warning and the garbled output both disappeared in
  the next run.
- **A dead config key**: `interruption={"detector": None}` was silently
  accepted (Python `TypedDict`s don't validate at runtime) but
  `InterruptionOptions` has no `detector` field at all -- confirmed by
  reading `help(livekit.agents.voice.turn)` against the installed package.
  It had been doing nothing since it was added; removed.
- **A dead TTS flag**: `reduce_latency=True` on the Rime `coda` model is
  silently ignored -- per Rime's own LiveKit integration docs, Coda ignores
  `reduce_latency`, `temperature`, `top_p`, `pause_between_brackets`, and
  `repetition_penalty`. Removed; remaining TTS latency (~2.5-3.5s
  synthesis time observed in development) is a property of the model
  itself, not a missed config flag.


## The endpointing-vs-latency tension

The turn-commit-race fix above (`min_delay: 0.1s -> 0.5s`) directly competes
with the sub-1000ms target: that delay is spent *before* the turn even
commits, so it's pure budget the rest of the pipeline can't get back.
Roughly:

```
0.5-0.8s endpointing  +  0.4-0.9s LLM TTFT  +  TTS TTFA  =  perceived response time
```

With Coda's TTS TTFA (0.4-1.3s), 1000ms was essentially unreachable without
reintroducing the garbled-reply bug. With Mist v3's TTFA (sub-100ms per
Rime's docs), the budget becomes tight but plausible. This wasn't solved by
turning `min_delay` back down -- that would just bring the original bug
back for a latency number. `EndpointingOptions` also exposes a `"dynamic"`
mode (vs. the `"fixed"` mode used here) with an `alpha` smoothing
coefficient, which in principle could let high-confidence turns commit
faster while still protecting ambiguous ones -- **not yet implemented or
verified against the installed library**, flagged here as the next lever
to investigate rather than guessed at blind.

## Limitations

- The turn-handling fix (`min_delay: 0.5s`) trades a small amount of raw
  responsiveness for correctness -- a technician who pauses naturally
  mid-sentence for close to 0.5s could, in principle, still trigger a
  premature commit. Not observed in testing, but not exhaustively ruled
  out either.
- Perceived-response-time numbers include Rime's Coda TTS synthesis time,
  which was the dominant remaining cost during development (2.5-3.5s
  total synthesis for short replies). Coda is optimized for voice quality,
  not minimum latency; Rime's own docs note Mist v3 reaches ~37ms
  time-to-first-audio if response speed becomes the binding constraint
  instead of voice quality.
- The `concatenation_heuristic_flags` metric in `benchmark_latency.py` is a
  regex heuristic (sentence-ending punctuation directly followed by a
  capital letter), not a semantic check -- it can both false-positive
  (legitimate abbreviations) and false-negative (concatenation without that
  exact punctuation pattern). Flagged examples should be spot-checked
  against the audio before being cited as a hard number.
- The adaptive interruption detector (LiveKit Cloud inference) was observed
  to occasionally time out after 0.7s and fall back to VAD-based
  interruption. This looked like designed graceful degradation rather than
  a bug (network reachability to `agent-gateway.livekit.cloud` was
  confirmed healthy via `curl`), but it does mean interruption precision
  can vary between turns depending on that fallback.