"""Synchronous-query, per-page lifetime, input, and fallback evidence gates."""
import datetime
import hashlib
import json
import math
import re
import statistics
from collections import Counter

from analyze import MIN_CHANGES, command, durations, load, locate_strip, ppm_image, require, stripe_geometry, trace_events, trace_occurrences

FALLBACK_EVENT = "RenderThreadJournal::MainThreadFallback"
SKIPPED_FOCUS_EVENT = "RenderThreadJournal::SkippedForFocus"
# Hybrid hand-off / hand-back model (schema 3).
TAKEOVER_EVENT = "ReplicaPage::TakeOver"
BEGIN_HANDBACK_EVENT = "RenderThreadJournal::BeginHandBack"
HANDBACK_EVENT = "RenderThreadJournal::HandBack"
ADOPTED_EVENT = "RenderThreadJournal::AnimationTimingsAdopted"
STOP_PRESENTING_EVENT = "ReplicaPage::StopPresenting"
UNREPLICABLE_EVENT = "RenderThreadJournal::Unreplicable"
UNREPLICABLE_LOG = "the render thread cannot reproduce this page"
HANDOFF_EVENTS = (TAKEOVER_EVENT, BEGIN_HANDBACK_EVENT, HANDBACK_EVENT, ADOPTED_EVENT, STOP_PRESENTING_EVENT)
REPLICA_PAINT_EVENT = "ReplicaPage::Paint"
MAIN_PAINT_EVENT = "LocalFrameView::RunPaintLifecyclePhase"
TAKEOVER_LIMIT_MS = 250
HANDBACK_LIMIT_MS = 1000
MEMORY_IDLE_MARGIN_MB = 48
RASTER_PROVIDER = re.compile(r"\[OMT\] replica \d+ raster provider (\d+)x(\d+) \((\w+)\)")
NVIDIA_VENDOR_ID = 0x10DE
# Read-only contract: RenderThreadQuery::Type in the parent's 153 render_thread_channel.h.
# No explicit enumerator assignments; preserve declaration order. Fail if the contract changes.
QUERY_TYPES = {name: index for index, name in enumerate((
    "OffsetLeft", "OffsetTop", "OffsetWidth", "OffsetHeight", "ClientLeft", "ClientTop",
    "ClientWidth", "ClientHeight", "ScrollLeft", "ScrollTop", "ScrollWidth", "ScrollHeight",
    "OffsetParent", "BoundingClientRect", "ClientRects", "ComputedStyle", "InnerText",
    "ElementFromPoint", "ElementsFromPoint", "HitTest", "FocusableState",
    "MouseRelativePosition", "RangeClientRects", "RangeBoundingClientRect",
    "InnerWidth", "InnerHeight", "WindowScrollX", "WindowScrollY", "AnimationTimings",
))}
# Only the hand-back fetch uses AnimationTimings; native-input families are
# answered on idle main now.
NOT_IN_QUERY_PAGE = ("HitTest", "MouseRelativePosition", "AnimationTimings")
LOG_PREFIX = re.compile(r"\[(\d+):(\d+):(\d{2})(\d{2})/(\d{2})(\d{2})(\d{2})\.(\d+):")


def events_from(directory):
    require(not load(directory / "trace-complete.json").get("dataLossOccurred", True), "Missing/lost trace")
    return trace_events(directory)


def thread_names(events):
    return {(event.get("pid"), event.get("tid")): event.get("args", {}).get("name") for event in events if event.get("ph") == "M" and event.get("name") == "thread_name"}


def on_threads(events, name, keys):
    return [event for event in trace_occurrences(events, name) if (event.get("pid"), event.get("tid")) in keys]


def render_keys(events, pid):
    return {key for key, name in thread_names(events).items() if key[0] == pid and name == "BlinkRenderThread"}


def takeovers(events, pid, start_ts, end_ts):
    return [event for event in on_threads(events, TAKEOVER_EVENT, render_keys(events, pid)) if start_ts <= event["ts"] <= end_ts]


def only_takeover(events, start, end):
    found = takeovers(events, start["pid"], start["ts"], end["ts"])
    require(len(found) == 1, f"Expected exactly one {TAKEOVER_EVENT} on the page's BlinkRenderThread during the block; found {len(found)}")
    return found[0]


def marker(events, name):
    found = [event for event in events if event.get("name") == f"validation:{name}" and "blink.user_timing" in event.get("cat", "")]
    require(len(found) == 1, f"Missing/ambiguous trace marker {name}")
    return found[0]


def log_records(text, reference_ms):
    year = datetime.datetime.fromtimestamp(reference_ms / 1000, datetime.timezone.utc).year
    records = []
    for line in text.splitlines():
        if "[OMT]" not in line:
            continue
        record = {"line": line, "epochMs": None, "pid": None, "tid": None}
        match = LOG_PREFIX.search(line)
        if match:
            pid, tid, month, day, hour, minute, second, fraction = match.groups()
            candidates = []
            for candidate_year in (year - 1, year, year + 1):
                try:
                    timestamp = datetime.datetime(candidate_year, int(month), int(day), int(hour), int(minute), int(second), int(fraction.ljust(6, "0")[:6]), tzinfo=datetime.timezone.utc).timestamp() * 1000
                    candidates.append(timestamp)
                except ValueError:
                    pass
            require(candidates, "Invalid Chromium log timestamp")
            record.update(epochMs=min(candidates, key=lambda value: abs(value - reference_ms)), pid=int(pid), tid=int(tid))
        records.append(record)
    return records


def case_logs(directory, case):
    raw = (directory.parent / "chrome.log").read_bytes()
    return log_records(raw[case["logStart"]:case["logEnd"]].decode(errors="replace"), case["startedMs"])


def windowed_occurrences(events, name, start, end):
    counts = Counter(before=0, during=0, after=0)
    details = []
    for event in trace_occurrences(events, name):
        when = "before" if event["ts"] < start["ts"] else "after" if event["ts"] > end["ts"] else "during"
        counts[when] += 1
        details.append({"window": when, **event})
    return {"traceCounts": dict(counts), "traceOccurrences": details}


def fallback_evidence(events, records, start, end, start_ms, end_ms):
    fallback = windowed_occurrences(events, FALLBACK_EVENT, start, end)
    skipped = windowed_occurrences(events, SKIPPED_FOCUS_EVENT, start, end)
    logs = []
    for record in records:
        match = re.search(r"main-thread (style|layout) fallback #(\d+) \(reason ([^)]+)\)", record["line"])
        if not match:
            continue
        epoch = record["epochMs"]
        when = "unknown" if epoch is None else "before" if epoch < start_ms else "after" if epoch > end_ms else "during"
        logs.append({**record, "phase": match[1], "counter": int(match[2]), "reason": match[3], "window": when})
    return {**fallback, "skippedForFocus": skipped, "loggedFallbacks": logs, "loggedCounts": dict(Counter(record["window"] for record in logs)), "zeroDuringBlock": fallback["traceCounts"]["during"] == 0 and not any(record["window"] in ("during", "unknown") for record in logs)}


def analyze_fallbacks(directory, case, run):
    events = events_from(directory)
    start, end = marker(events, "block-start"), marker(events, "block-end")
    result = fallback_evidence(events, case_logs(directory, case), start, end, case["block"]["start"]["epochMs"], case["block"]["end"]["epochMs"])
    (directory / "fallbacks.json").write_text(json.dumps(result, indent=2) + "\n")
    require(run.get("fallbackTraceEvent") == FALLBACK_EVENT, "All-occurrence fallback trace instrumentation not confirmed; throttled logs cannot prove zero")
    require(result["zeroDuringBlock"], "Main-thread style/layout fallback during block (or fallback timestamp unavailable)")
    return result


def query_samples(block, mode):
    samples = block["samples"]
    ms = block["ms"]
    require(len(samples) >= ms // 250, "Missing ~200ms query samples")
    times = [sample["t"] for sample in samples]
    require(times[0] < 500 and times[-1] >= ms, "Query samples do not cover the task")
    require(all(0 < b - a < 500 for a, b in zip(times, times[1:])), "Query sampling stalled or repeated timestamps")
    checks = block["assertions"]["checks"]
    require(len(checks) >= 45 and len({check["name"] for check in checks}) == len(checks), "Missing/duplicate mutation/query assertions")
    failed = [check["name"] for check in checks if not check["passed"] or check.get("actual") != check["expected"]]
    require(not failed, f"Immediate query mismatches: {failed}")
    require(block["heartbeatBefore"] == block["heartbeatAfter"], "Task yielded while querying")
    window_scroll = block.get("scope", {}).get("windowScroll", {})
    if window_scroll.get("required"):
        restored = window_scroll.get("restoredAtMs")
        require(isinstance(restored, (int, float)) and math.isfinite(restored) and 0 <= restored < 250, "Window scroll not restored before guarded pixel sampling")
    summary = {}
    for panel in ("height", "grid"):
        channels = {}
        for channel in ("offset", "rect", "computed"):
            values = [sample[panel][channel] for sample in samples]
            require(all(isinstance(value, (float, int)) and math.isfinite(value) and 23 <= value <= 265 for value in values), f"Invalid {panel}/{channel} query value")
            channels[channel] = {"min": min(values), "max": max(values), "final": values[-1]}
            if mode == "omt":
                require(abs(values[-1] - 264) <= (1 if channel == "offset" else 0.1), f"{panel}/{channel}: final query did not reach 264px inside task")
                active = [value for sample, value in zip(samples, values) if 200 <= sample["t"] <= ms * 0.8 - 200]
                require(len(active) >= 5 and all(b > a for a, b in zip(active, active[1:])), f"{panel}/{channel}: samples not strictly increasing during transition")
                require(all(b >= a - 0.1 for a, b in zip(values, values[1:])), f"{panel}/{channel}: query values went backwards")
        for sample in samples:
            values = list(sample[panel].values())
            require(max(values) - min(values) <= 8, f"{panel}: inconsistent offset/rect/computed queries (>8px; serial-query timing allowance)")
        summary[panel] = channels
    return {"samples": len(samples), "assertions": len(checks), "panels": summary, "outsideShadow": block["assertions"]["outsideShadow"], "scopeObservations": block.get("scope", {})}


def query_roundtrips(events, start, end, mode, minimum=1, after=None):
    """Pairs in [max(start, after), end]; `after` is the TakeOver timestamp."""
    names = thread_names(events)
    main = (start["pid"], start["tid"])
    require(names.get(main) == "CrRendererMain", "Query dispatch is not on CrRendererMain")
    lower = start["ts"] if after is None else max(start["ts"], after)
    slices = list(durations(events))
    requests = [event for event in slices if event.get("name") == "RenderThread::RunQuery" and (event.get("pid"), event.get("tid")) == main and lower <= event["ts"] <= end["ts"]]
    answers = [event for event in slices if event.get("name") == "ReplicaPage::AnswerQuery" and event.get("pid") == main[0] and lower <= event["ts"] <= end["ts"]]
    if mode == "baseline":
        require(not requests and not answers, "Baseline unexpectedly forwarded synchronous queries")
        return {"requests": 0, "answers": 0}
    require(len(requests) >= minimum and len(answers) >= minimum, "Missing synchronous RunQuery / AnswerQuery trace pairs")
    used = set()
    pairs = []
    for request in requests:
        matches = [(index, answer) for index, answer in enumerate(answers) if index not in used and names.get((answer["pid"], answer["tid"])) == "BlinkRenderThread" and answer["tid"] != main[1] and request["ts"] <= answer["ts"] and answer["ts"] + answer.get("dur", 0) <= request["ts"] + request.get("dur", 0) and request.get("args", {}).get("type") == answer.get("args", {}).get("type")]
        require(len(matches) == 1, "RunQuery does not enclose exactly one same-type render-thread answer")
        index, answer = matches[0]
        used.add(index)
        pairs.append({"mainPid": main[0], "mainTid": main[1], "renderTid": answer["tid"], "type": request.get("args", {}).get("type"), "queryUs": request.get("dur", 0), "answerUs": answer.get("dur", 0)})
    require(len(used) == len(answers), "Unpaired render-thread query answers")
    require(len({pair["renderTid"] for pair in pairs}) <= 1, "One document queried multiple render threads")
    return {"requests": len(requests), "answers": len(answers), "maxQueryUs": max((pair["queryUs"] for pair in pairs), default=0), "typeCounts": dict(Counter(pair["type"] for pair in pairs)), "pairs": pairs}


def window_scroll_restore(events, start, end):
    restored = marker(events, "window-scroll-restored")
    require((restored["pid"], restored["tid"]) == (start["pid"], start["tid"]) and start["ts"] <= restored["ts"] < min(start["ts"] + 250000, end["ts"]), "Window scroll restoration trace missing from pre-guard main-thread task")
    return {"mainPid": restored["pid"], "mainTid": restored["tid"], "restoredAtMs": (restored["ts"] - start["ts"]) / 1000}


def analyze_queries(directory, case):
    result = query_samples(case["block"], case["mode"])
    events = events_from(directory)
    start, end = marker(events, "block-start"), marker(events, "block-end")
    if case["block"].get("scope", {}).get("windowScroll", {}).get("required"):
        result["windowScrollRestore"] = window_scroll_restore(events, start, end)
    # Before TakeOver main answers queries itself; only [TakeOver, block end] is forwarded.
    after = only_takeover(events, start, end)["ts"] if case["mode"] == "omt" else None
    result["roundtrips"] = query_roundtrips(events, start, end, case["mode"], len(case["block"]["samples"]) * 6, after)
    if case["mode"] == "omt":
        observed = {pair["type"] for pair in result["roundtrips"]["pairs"]}
        missing = [name for name, value in QUERY_TYPES.items() if name not in NOT_IN_QUERY_PAGE and value not in observed]
        require(not missing, f"Query types not forwarded (or enum contract changed): {missing}")
        result["queryTypeContract"] = QUERY_TYPES
        lines = "\n".join(record["line"] for record in case_logs(directory, case))
        require("answered its first layout query on the render thread" in lines, "Missing first render-thread layout-query answer log")
        require("main thread got its first layout answer from the render thread" in lines, "Missing first main-thread layout-answer log")
    (directory / "queries-analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def outside_fallbacks(events, records):
    occurrences = trace_occurrences(events, FALLBACK_EVENT)
    skipped = trace_occurrences(events, SKIPPED_FOCUS_EVENT)
    return {"unthrottledTraceCount": len(occurrences), "traceOccurrences": occurrences, "skippedForFocus": {"unthrottledTraceCount": len(skipped), "traceOccurrences": skipped}, "loggedFallbacks": [record for record in records if re.search(r"main-thread (style|layout) fallback #", record["line"])], "note": "No busy-loop window in this smoke case; fallbacks reported, not treated as in-block violations. SkippedForFocus is informational and never subtracts from fallback counts."}


def validate_input(directory, mode):
    result = load(directory / "input/input.json")
    require(result["completed"], "Input milestones incomplete")
    events = result["events"]
    require([event["type"] for event in events] == ["mousedown", "mouseup", "click"], "Native input event sequence mismatch")
    for event in events:
        require(event["target"] == "input-button" and event["isTrusted"] and event["button"] == 0, "Native input target/trust mismatch")
        require(abs(event["offsetX"] - 20) <= 1 and abs(event["offsetY"] - 15) <= 1, "Native input offset mismatch")
    require(result["focused"] == "input-button", "Native click failed focusability")
    trace = events_from(directory / "input")
    result["fallbacks"] = outside_fallbacks(trace, case_logs(directory / "input", result))
    # Input arrives while main is idle: hit tests are answered on main, so no
    # forwarded pair is required. Any pair that does occur must still be exact.
    result["roundtrips"] = query_roundtrips(trace, marker(trace, "input-start"), marker(trace, "input-end"), mode, minimum=0)
    return result


def lifecycle_pixel_verdict(frames):
    expected = {"owner-a": 64, "owner-b": 24, "restored-a": 64, "restored-mutated-a": 96}
    require(set(frames) == set(expected), "BFCache pixel milestones missing")
    for name, height in expected.items():
        frame = frames[name]
        require(frame["cyanHeight"] == height and frame["followerY"] == height, f"BFCache {name}: stale/incorrect layout pixels")
    require(frames["owner-a"]["sha256"] == frames["restored-a"]["sha256"], "Restored A pixels differ from saved DOM state")
    require(frames["owner-b"]["sha256"] != frames["restored-a"]["sha256"], "Restored A is a stale B surface")
    require(frames["restored-mutated-a"]["sha256"] not in {frames["owner-a"]["sha256"], frames["owner-b"]["sha256"]}, "Restored mutation is only an old cached surface")
    return frames


def lifecycle_pixels(folder):
    frames = {}
    roi = None
    for name in ("owner-a", "owner-b", "restored-a", "restored-mutated-a"):
        roi, frames[name] = frame_geometry(folder / f"{name}-x11.png", roi)
    return {"roi": roi, "frames": lifecycle_pixel_verdict(frames)}


def lifecycle_evidence(directory, mode):
    result = load(directory / "page-threads/threads.json")
    require(result["completed"], "Page-thread lifecycle milestones incomplete")
    stages = result["stages"]
    require([stage["name"] for stage in stages] == ["one-page", "two-pages", "peer-closed", "owner-navigated", "owner-restored"], "Lifecycle stages missing")
    events = events_from(directory / "page-threads")
    a, peer, b, restored, mutation, block_end, back_end = (marker(events, name) for name in ("page-a", "page-peer", "page-b", "page-a-restored", "restored-mutation", "restored-block-end", "history-back-end"))
    require(a["pid"] == peer["pid"] and a["tid"] == peer["tid"], "Same-origin pages did not demonstrably share a renderer main thread")
    require((a["pid"], a["tid"]) == (restored["pid"], restored["tid"]), "BFCache did not restore the original main-thread document")
    require(restored["ts"] < mutation["ts"] < block_end["ts"] < back_end["ts"], "Restored-paint trace milestones out of order")
    expected = [1, 2, 1, 1, 1] if mode == "omt" else [0, 0, 0, 0, 0]
    require([len(stage["renderThreads"]) for stage in stages] == expected, "Incorrect per-page render-thread counts")
    result["fallbacks"] = outside_fallbacks(events, case_logs(directory / "page-threads", result))
    cached = result["bfcache"]
    require(cached["pageshow"].get("persisted") is True and cached["pageshow"].get("url") == result["urlA"], "BFCache hit not demonstrated by pageshow.persisted")
    require(cached["original"]["height"] == cached["restored"]["height"] == 64 and cached["onB"]["height"] == 24 and cached["mutated"]["height"] == 96, "BFCache geometry mutation/restore mismatch")
    require(all(cached[name]["token"] == cached["expectedToken"] for name in ("original", "restored", "mutated")) and cached["onB"]["token"] is None, "BFCache did not preserve existing A DOM identity")
    cached["pixels"] = lifecycle_pixels(directory / "page-threads")
    cached["roundtrips"] = query_roundtrips(events, restored, back_end, mode, minimum=2)
    if mode == "baseline":
        found = Counter(event["name"] for name in HANDOFF_EVENTS for event in trace_occurrences(events, name))
        require(not found, f"Flag-off baseline emitted hand-off events: {dict(found)}")
        return result
    require(a["pid"] == b["pid"], "Navigation changed renderer process; same-process replacement evidence unavailable")
    inventory = {(event.get("pid"), event.get("tid")): event.get("args", {}).get("name") for event in events if event.get("ph") == "M" and event.get("name") == "thread_name"}
    raw = (directory / "chrome.log").read_bytes()
    records = log_records(raw[result["logStart"]:result["logEnd"]].decode(errors="replace"), result["startedMs"])
    created = []
    for record in records:
        match = re.search(r"replica (\d+) created on render thread", record["line"])
        if match:
            created.append({**record, "replica": int(match[1])})
    for stage in stages:
        require(all(thread["pid"] == a["pid"] and thread["comm"] == "BlinkRenderThread"[:15] for thread in stage["renderThreads"]), "proc thread PID/name mismatch")
        for thread in stage["renderThreads"]:
            require(inventory.get((thread["pid"], thread["tid"])) == "BlinkRenderThread", "proc TID lacks full BlinkRenderThread trace metadata")
    require(len({thread["tid"] for thread in stages[1]["renderThreads"]}) == 2, "Two pages share one render TID")
    require(stages[2]["renderThreads"] == stages[0]["renderThreads"], "Peer close did not preserve owner thread")
    require(stages[3]["renderThreads"] != stages[0]["renderThreads"], "Navigation did not retire old thread identity")
    require(stages[4]["renderThreads"] not in (stages[0]["renderThreads"], stages[3]["renderThreads"]), "BFCache reused a stopped render-thread identity")
    restored_thread = stages[4]["renderThreads"][0]
    require(all(pair["renderTid"] == restored_thread["tid"] for pair in cached["roundtrips"]["pairs"]), "Restored queries did not reach the new page thread")
    require(sum(pair["type"] == QUERY_TYPES["OffsetHeight"] for pair in cached["roundtrips"]["pairs"]) >= 2, "Restored and freshly mutated offsetHeight queries missing")
    # The restored page is idle until the long task: TakeOver + Paint must come
    # from the NEW thread inside [restored-mutation, restored-block-end].
    takeover = only_takeover(events, mutation, block_end)
    require(takeover["tid"] == restored_thread["tid"], "Restored-page TakeOver is not on the new render thread")
    cached["takeoverLatencyMs"] = (takeover["ts"] - mutation["ts"]) / 1000
    paints = [event for event in on_threads(events, REPLICA_PAINT_EVENT, {(restored_thread["pid"], restored_thread["tid"])}) if takeover["ts"] <= event["ts"] <= block_end["ts"]]
    require(paints, "Restored page has no fresh new-thread Paint inside its long task")
    cached["freshPaints"] = len(paints)
    identities = []
    for stage in (stages[0], stages[1], stages[3], stages[4]):
        stage_ids = []
        for thread in stage["renderThreads"]:
            matches = [record for record in created if record["pid"] == thread["pid"] and record["tid"] == thread["tid"] and record["epochMs"] is not None and record["epochMs"] <= stage["epochMs"]]
            require(matches, "Live render TID has no timestamped replica-created log")
            stage_ids.append(max(matches, key=lambda record: record["epochMs"])["replica"])
        identities.append(stage_ids)
    require(len(set(identities[1])) == 2, "Two pages did not receive two replica IDs")
    require(identities[2][0] not in identities[1], "Navigation did not allocate a new replica ID")
    require(identities[3][0] not in identities[1] + identities[2], "BFCache restore did not allocate a new replica ID")
    attached = []
    for record in records:
        match = re.search(r'render thread journal attached to "?([^"\s]+)"?', record["line"])
        if match:
            attached.append({**record, "url": match[1]})
    for url in (result["urlA"], result["urlPeer"], result["urlB"]):
        require(any(record["url"] == url for record in attached), f"Journal-attach URL milestone missing: {url}")
    require(any(record["url"] == result["urlA"] and record["epochMs"] is not None and result["historyBackStartedMs"] <= record["epochMs"] <= stages[4]["epochMs"] for record in attached), "BFCache restore missing a fresh journal attachment")
    for replica in set(identities[1] + identities[2] + identities[3]):
        require(any(f"render thread started for replica {replica}" in record["line"] for record in records), "Replica-start milestone missing")
    stops = [record for record in records if re.search(r"\[OMT\] render thread stopped\s*$", record["line"]) and record["epochMs"] is not None]
    cache_stops = [record for record in records if "page entered the back/forward cache; render thread stopped" in record["line"] and record["epochMs"] is not None]
    require(any(result["peerCloseStartedMs"] <= record["epochMs"] <= stages[2]["epochMs"] for record in stops), "Peer close missing thread-stopped log")
    require(any(result["navigationStartedMs"] <= record["epochMs"] <= stages[3]["epochMs"] for record in stops), "Navigation missing old-thread-stopped log")
    require(any(result["navigationStartedMs"] <= record["epochMs"] <= stages[3]["epochMs"] for record in cache_stops), "A entering BFCache missing thread-stopped log")
    require(any(result["historyBackStartedMs"] <= record["epochMs"] <= stages[4]["epochMs"] for record in stops), "History back did not stop B's render thread")
    cached["cacheEntryStopLogs"] = cache_stops
    result["replicaIdsByStage"] = identities
    result["stoppedLogs"] = stops
    return result


def handoff_evidence(events, mode, start, end):
    """TakeOver early in the block; hand-back after it; replica stops painting."""
    main = (start["pid"], start["tid"])
    if mode != "omt":
        found = Counter(event["name"] for name in HANDOFF_EVENTS for event in trace_occurrences(events, name))
        require(not found, f"Flag-off baseline emitted hand-off events: {dict(found)}")
        return {"handoffEvents": 0}
    takeover = only_takeover(events, start, end)
    latency = (takeover["ts"] - start["ts"]) / 1000
    require(latency <= TAKEOVER_LIMIT_MS, f"TakeOver {latency:.1f}ms after block start (limit {TAKEOVER_LIMIT_MS}ms)")
    render = (takeover["pid"], takeover["tid"])

    def after_block(name, key):
        return [event for event in on_threads(events, name, {key}) if event["ts"] > end["ts"]]

    begins, handbacks = after_block(BEGIN_HANDBACK_EVENT, main), after_block(HANDBACK_EVENT, main)
    require(len(begins) == 1 and len(handbacks) == 1, f"Expected one BeginHandBack and one HandBack on main after block end; found {len(begins)}/{len(handbacks)}")
    begin, handback = begins[0], handbacks[0]
    require(begin["ts"] <= handback["ts"], "HandBack precedes BeginHandBack")
    handback_ms = (handback["ts"] - end["ts"]) / 1000
    require(handback_ms <= HANDBACK_LIMIT_MS, f"HandBack {handback_ms:.1f}ms after block end (limit {HANDBACK_LIMIT_MS}ms)")
    adopted = [event for event in on_threads(events, ADOPTED_EVENT, {main}) if begin["ts"] <= event["ts"] <= handback["ts"]]
    require(len(adopted) == 1, f"Expected one AnimationTimingsAdopted between BeginHandBack and HandBack; found {len(adopted)}")
    timings = query_roundtrips(events, begin, handback, "omt", minimum=1)
    types = [pair["type"] for pair in timings["pairs"]]
    require(types == [QUERY_TYPES["AnimationTimings"]], f"Hand-back must make exactly one AnimationTimings (28) query; saw types {types}")
    require(timings["pairs"][0]["renderTid"] == render[1], "Animation timings not answered by the taking-over render thread")
    stops = after_block(STOP_PRESENTING_EVENT, render)
    require(len(stops) == 1, f"Expected one ReplicaPage::StopPresenting after block end; found {len(stops)}")
    replica_paints = on_threads(events, REPLICA_PAINT_EVENT, {render})
    late = [event["ts"] for event in replica_paints if event["ts"] > stops[0]["ts"]]
    require(not late, f"{len(late)} ReplicaPage::Paint after StopPresenting (first ts {late[:1]})")
    main_paints = [event for event in on_threads(events, MAIN_PAINT_EVENT, {main}) if event["ts"] > end["ts"]]
    resumed = [event for event in main_paints if event["ts"] > handback["ts"]]
    require(main_paints and resumed, f"Main-thread paint ({MAIN_PAINT_EVENT}) did not resume after hand-back")
    in_block = [event for event in replica_paints if takeover["ts"] <= event["ts"] <= end["ts"]]
    require(len(in_block) >= MIN_CHANGES, "Too few ReplicaPage::Paint on the taking-over thread during the block")
    fallbacks = trace_occurrences(events, FALLBACK_EVENT)
    outside = [event for event in fallbacks if not takeover["ts"] <= event["ts"] <= begin["ts"]]
    return {
        "renderPid": render[0], "renderTid": render[1],
        "takeoverLatencyMs": latency, "takeoverArgs": takeover.get("args", {}),
        "beginHandBackAfterEndMs": (begin["ts"] - end["ts"]) / 1000, "handBackAfterEndMs": handback_ms,
        "stopPresentingAfterEndMs": (stops[0]["ts"] - end["ts"]) / 1000,
        "animationTimingsAdopted": adopted[0].get("args", {}), "animationTimingsQueryUs": timings["maxQueryUs"],
        "replicaPaintsInBlock": len(in_block), "mainPaintsAfterEnd": len(main_paints), "mainPaintsAfterHandBack": len(resumed),
        # Informational: fallbacks should only occur while R renders.
        "fallbacksOutsideRendering": len(outside),
    }


def analyze_handoff(directory, case):
    events = events_from(directory)
    result = handoff_evidence(events, case["mode"], marker(events, "block-start"), marker(events, "block-end"))
    (directory / "handoff.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def smoke_trace_evidence(directory, mode):
    """Idle DOM/CSSOM mutations: main paints; the replica follows but never paints."""
    events = events_from(directory / "smoke-trace")
    first = marker(events, "smoke-insert")
    main = (first["pid"], first["tid"])
    replica = [event for event in events if event.get("name", "").startswith("ReplicaPage::") and event.get("ph") in ("X", "B", "I", "i")]
    counts = Counter(event["name"] for event in replica)
    main_paints = [event for event in on_threads(events, MAIN_PAINT_EVENT, {main}) if event["ts"] >= first["ts"]]
    require(len(main_paints) >= 6, f"Idle smoke mutations: only {len(main_paints)} main-thread paints")
    if mode == "omt":
        following = [event for event in replica if (event["pid"], event["tid"]) in render_keys(events, main[0]) and event["name"] in ("ReplicaPage::Follow", "ReplicaPage::ApplyOps")]
        require(following, "Replica did not follow idle mutations (no ReplicaPage::Follow/ApplyOps)")
        require(not counts.get(REPLICA_PAINT_EVENT) and not counts.get(TAKEOVER_EVENT), f"Idle mutations caused render-thread takeover/paint: {dict(counts)}")
    else:
        require(not replica, f"Flag-off baseline emitted replica events: {dict(counts)}")
    return {"mainPaints": len(main_paints), "replicaEvents": dict(counts)}


def frame_geometry(path, roi=None):
    data = command(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-threads", "1", "-f", "image2pipe", "-c:v", "ppm", "pipe:1"])
    width, height, pixels = ppm_image(data)
    require((width, height) == (1280, 800), "Capture dimensions changed")
    roi = roi or locate_strip(width, height, pixels)
    strip = b"".join(pixels[(y * width + roi["x"]) * 3:(y * width + roi["x"] + roi["width"]) * 3] for y in range(roi["y"], roi["y"] + roi["height"]))
    cyan_height, follower = stripe_geometry(strip, roi["width"], roi["height"])
    return roi, {"cyanHeight": cyan_height, "followerY": follower, "sha256": hashlib.sha256(strip).hexdigest()}


def validate_unreplicable(directory):
    """OMT only: detach logged + traced, no TakeOver/Paint, stock rendering reaches 264px."""
    folder = directory / "unreplicable"
    result = load(folder / "unreplicable.json")
    require(result["completed"], "Unreplicable milestones incomplete")
    events = events_from(folder)
    lines = [record["line"] for record in case_logs(folder, result)]
    require(any(UNREPLICABLE_LOG in line for line in lines), f"Missing '[OMT] {UNREPLICABLE_LOG}' log line")
    instants = trace_occurrences(events, UNREPLICABLE_EVENT)
    require(instants, f"Missing {UNREPLICABLE_EVENT} trace instant")
    for name in (TAKEOVER_EVENT, REPLICA_PAINT_EVENT):
        require(not trace_occurrences(events, name), f"Unreplicable page emitted {name}")
    frame = frame_geometry(folder / "after-x11.png")[1]
    require(frame["cyanHeight"] == frame["followerY"] == 264, f"Unreplicable page did not render final 264px geometry: {frame}")
    return {"unreplicableInstants": len(instants), "after": result["after"], "frame": frame}


def median(values):
    require(values, "Empty memory window")
    return statistics.median(values)


def memory_evidence(directory, mode):
    result = load(directory / "mem/memory.json")
    require(result["completed"], "Memory churn milestones incomplete")
    events = events_from(directory / "mem")
    start, end = marker(events, "churn-start"), marker(events, "churn-end")
    churn_start, churn_ms = result["churnStart"]["epochMs"], result["churnEnd"]["epochMs"] - result["churnStart"]["epochMs"]
    require(result["churnEnd"]["ticks"] >= 500, "Churn page did not run its 16ms tasks")
    series = []
    for sample in result["samples"]:
        entry = next((renderer for renderer in sample["renderers"] if renderer["pid"] == start["pid"]), None)
        require(entry and entry.get("pssKb"), "Page renderer missing from a PSS sample")
        series.append({"t": sample["epochMs"] - churn_start, "pssMb": entry["pssKb"] / 1024, "renderThreads": entry["renderThreads"]})
    require(len(series) >= 20 and series[-1]["t"] >= churn_ms + 20000, "PSS sampling incomplete")
    churn = [item for item in series if item["t"] <= churn_ms]
    require(all((item["renderThreads"] >= 1) == (mode == "omt") for item in churn), "Churn page renderer render-thread presence does not match mode")
    warm = median([item["pssMb"] for item in series if 5000 <= item["t"] < 10000])
    last = median([item["pssMb"] for item in churn if item["t"] >= churn_ms - 5000])
    idle = median([item["pssMb"] for item in series if item["t"] > churn_ms and item["t"] >= series[-1]["t"] - 10000])
    gpu = [(sample["epochMs"] - churn_start, sample.get("gpu") or {}) for sample in result["samples"]]
    def gpu_median(key, scale, idle):
        values = [entry[key] / scale for t, entry in gpu if entry.get(key) is not None and (t > churn_ms if idle else t <= churn_ms)]
        return statistics.median(values) if values else None
    during = takeovers(events, start["pid"], start["ts"], end["ts"])
    require(not during, f"{len(during)} TakeOver during short-task churn")
    require(not trace_occurrences(events, UNREPLICABLE_EVENT), "Churn page unexpectedly unreplicable")
    if mode == "omt":
        require(last <= warm * 1.5 + 20, f"OMT churn PSS grows: last-5s median {last:.1f}MB > 1.5 x {warm:.1f}MB + 20MB")
    return {"pid": start["pid"], "ticks": result["churnEnd"]["ticks"], "takeoversDuringChurn": len(during), "takeoversTotal": len(trace_occurrences(events, TAKEOVER_EVENT)), "warmChurnMedianMb": warm, "lastChurnMedianMb": last, "idleMedianMb": idle,
        # Informational: GPU process PSS and (real display only) its VRAM.
        "gpuProcess": {"churnPssMb": gpu_median("pssKb", 1024, False), "idlePssMb": gpu_median("pssKb", 1024, True), "churnVramMib": gpu_median("vramMib", 1, False), "idleVramMib": gpu_median("vramMib", 1, True)},
        "series": series}


def gpu_evidence(directory, mode, run):
    """Real-display runs: SystemInfo must show NVIDIA hardware acceleration; OMT replicas must raster on the GPU."""
    info = run["gpu"][mode]
    primary = info["devices"][0]
    features = info["featureStatus"]
    require(primary["vendorId"] == NVIDIA_VENDOR_ID and "NVIDIA" in info.get("glRenderer", ""), f"Active GPU is not NVIDIA: vendor {primary['vendorId']:#x}, {info.get('glRenderer')}")
    require(features.get("gpu_compositing") == "enabled" and features.get("rasterization", "").startswith("enabled"), f"GPU compositing/rasterization not hardware accelerated: {features}")
    lines = [line for line in (directory / "chrome.log").read_text(errors="replace").splitlines() if RASTER_PROVIDER.search(line)]
    kinds = Counter(RASTER_PROVIDER.search(line).group(3) for line in lines)
    if mode == "omt":
        require(kinds["gpu"] >= 1, "OMT: no '[OMT] replica N raster provider WxH (gpu)' log line")
        require(set(kinds) == {"gpu"}, f"OMT: non-GPU replica raster providers {dict(kinds)}")
    else:
        require(not lines, "Baseline logged OMT raster providers")
    return {"glRenderer": info["glRenderer"], "glImplementationParts": info.get("glImplementationParts"), "vendorId": primary["vendorId"], "driverVersion": primary.get("driverVersion"), "featureStatus": {key: features.get(key) for key in ("gpu_compositing", "rasterization", "opengl")}, "rasterProviders": dict(kinds), "rasterProviderLines": lines[:10]}


def compare_memory(baseline, omt):
    limit = baseline["idleMedianMb"] + MEMORY_IDLE_MARGIN_MB
    require(omt["idleMedianMb"] <= limit, f"OMT idle PSS {omt['idleMedianMb']:.1f}MB > baseline {baseline['idleMedianMb']:.1f}MB + {MEMORY_IDLE_MARGIN_MB}MB")
    return {"baselineIdleMb": baseline["idleMedianMb"], "omtIdleMb": omt["idleMedianMb"], "deltaMb": omt["idleMedianMb"] - baseline["idleMedianMb"], "limitMb": limit}


def compare_extended(output, cases):
    comparisons = []
    for ms in (3000, 10000):
        pair = {case["mode"]: case for case in cases if case["kind"] == "queries" and case["ms"] == ms}
        require(set(pair) == {"baseline", "omt"}, "Missing paired synchronous-query cases")
        baseline, omt = (pair[mode]["block"] for mode in ("baseline", "omt"))
        require(baseline["assertions"] == omt["assertions"], "Baseline/OMT differ on immediate DOM/CSSOM/shadow/focus results")
        comparisons.append({"ms": ms, "immediateAssertionsEqual": True, "baselineSamples": baseline["samples"], "omtSamples": omt["samples"]})
    baseline, omt = (load(output / mode / "input/input.json") for mode in ("baseline", "omt"))
    require(len(baseline.get("events", [])) == len(omt.get("events", [])) == 3, "Input comparison missing events")
    for left, right in zip(baseline["events"], omt["events"]):
        require(all(left[key] == right[key] for key in ("type", "target", "button", "isTrusted")), "Baseline/OMT input semantics differ")
        require(abs(left["offsetX"] - right["offsetX"]) <= 1 and abs(left["offsetY"] - right["offsetY"]) <= 1, "Baseline/OMT native input offsets differ")
    return {"queries": comparisons, "nativeInputEqual": True}
