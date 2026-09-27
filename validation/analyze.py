#!/usr/bin/env python3
"""Fail-closed pixel + thread evidence. Python standard library and existing FFmpeg only."""
import argparse
import functools
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

CYAN = bytes((32, 216, 192))
YELLOW = bytes((248, 205, 70))
GUARD_MS = 250
MIN_CHANGES = 5
MIN_SPAN_MS = 500


def command(args, timeout=60):
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed {args}: {result.stderr.decode(errors='replace')[-4000:]}")
    return result.stdout


def load(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


@functools.lru_cache(maxsize=1)
def _trace_events(path, _mtime_ns, _size):
    trace = load(Path(path))
    return trace["traceEvents"] if isinstance(trace, dict) else trace


def trace_events(directory):
    """Parse each (large) trace once for the several analyses of one case."""
    path = directory / "trace.json"
    stat = path.stat()
    return _trace_events(str(path), stat.st_mtime_ns, stat.st_size)


def trace_occurrences(events, name):
    # Count events, not the throttled textual counter. B/E slices count once.
    return [event for event in events if event.get("name") == name and event.get("ph") in ("X", "B", "I", "i")]


def ppm_image(data):
    header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
    require(header is not None, "Invalid PPM frame")
    width, height = map(int, header.groups())
    pixels = data[header.end():]
    require(len(pixels) == width * height * 3, "Truncated PPM")
    return width, height, pixels


def locate_strip(width, height, pixels, occurrence=0):
    # Derive the capture-space ROI from actual pixels, NOT assumed Chrome decorations.
    needle = CYAN * 64
    offset = pixels.find(needle)
    require(offset >= 0 and offset % 3 == 0, "Initial cyan layout panel missing from external capture")
    y, x = divmod(offset // 3, width)
    for index in range(occurrence + 1):
        right = x
        while right < width and pixels[(y * width + right) * 3:(y * width + right + 1) * 3] == CYAN:
            right += 1
        if index < occurrence:
            next_offset = pixels.find(needle, (y * width + right) * 3, (y + 1) * width * 3)
            require(next_offset >= 0 and next_offset % 3 == 0, "Second layout panel missing from capture")
            x = (next_offset // 3) % width
    require(right - x >= 300, "Initial cyan panel too narrow / wrong surface")
    require(y + 290 <= height, "Proof region clipped")
    # Right edge avoids yellow label glyphs; includes cyan height and normal-flow yellow sibling.
    return {"x": right - 48, "y": y, "width": 32, "height": 290}


def stripe_geometry(frame, width=32, height=290):
    cyan_rows, yellow_rows = [], []
    for y in range(height):
        row = frame[y * width * 3:(y + 1) * width * 3]
        if row.count(CYAN) >= width - 2:
            cyan_rows.append(y)
        if row.count(YELLOW) >= width - 2:
            yellow_rows.append(y)
    return len(cyan_rows), min(yellow_rows) if yellow_rows else None


def pixel_verdict(samples, start_ms, end_ms, mode):
    interior = [sample for sample in samples if start_ms + GUARD_MS <= sample["epochMs"] <= end_ms - GUARD_MS]
    require(len(interior) >= 15, "Too few captured frames strictly inside the busy loop")
    gaps = [b["epochMs"] - a["epochMs"] for a, b in zip(interior, interior[1:])]
    require(max(gaps, default=0) <= 250, "Capture gap >250ms inside block; evidence incomplete")
    require(interior[0]["epochMs"] <= start_ms + GUARD_MS + 150, "Capture misses early block")
    require(interior[-1]["epochMs"] >= end_ms - GUARD_MS - 150, "Capture misses late block")
    changes = []
    for before, after in zip(interior, interior[1:]):
        if after["cyanHeight"] != before["cyanHeight"]:
            changes.append(after["epochMs"])
    heights = [sample["cyanHeight"] for sample in interior]
    followers = [sample["followerY"] for sample in interior]
    require(all(y is not None for y in followers), "Normal-flow sibling missing from captured proof strip")
    require(all(abs(sample["cyanHeight"] - sample["followerY"]) <= 1 for sample in interior), "Yellow sibling is not following cyan layout edge")
    summary = {
        "interiorFrames": len(interior),
        "uniqueRoiHashes": len({sample["sha256"] for sample in interior}),
        "heightChangeSteps": len(changes),
        "heightRangePx": max(heights) - min(heights),
        "changeSpanMs": changes[-1] - changes[0] if len(changes) > 1 else 0,
        "interiorStartEpochMs": interior[0]["epochMs"],
        "interiorEndEpochMs": interior[-1]["epochMs"],
        "maxCaptureGapMs": max(gaps, default=0),
        "capturedFps": (len(interior) - 1) * 1000 / (interior[-1]["epochMs"] - interior[0]["epochMs"]),
    }
    if mode == "omt":
        require(len(changes) >= MIN_CHANGES, f"OMT: fewer than {MIN_CHANGES} layout pixel changes during block")
        require(summary["heightRangePx"] >= 30, "OMT: layout edge moved <30px during block")
        require(summary["changeSpanMs"] >= MIN_SPAN_MS, "OMT: only a jump / too short a change interval")
        require(all(b >= a - 1 for a, b in zip(heights, heights[1:])), "OMT: non-monotonic layout surface")
        # Hand-back continuity: no jump back / flash from block start to the end of the recording.
        tail = [sample["cyanHeight"] for sample in samples if sample["epochMs"] >= start_ms]
        drops = [(index, a, b) for index, (a, b) in enumerate(zip(tail, tail[1:])) if b < a]
        require(not drops, f"OMT: captured height decreased after block start (hand-back flash/jump back): first {drops[:3]}")
        # The 264px end state is enforced for every mode in analyze_pixels.
        summary["continuityFrames"] = len(tail)
    else:
        require(summary["heightRangePx"] == 0 and len(changes) == 0 and summary["uniqueRoiHashes"] == 1, "Baseline layout changed during block: invalid negative control")
    return summary


def analyze_pixels(directory, case, roi_index=0):
    video = directory / "capture.mkv"
    probe = json.loads(command(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(video)]))
    times = [float(frame["best_effort_timestamp_time"]) * 1000 for frame in probe["frames"]]
    require(len(times) >= 30, "Recording too short")
    require(all(b > a for a, b in zip(times, times[1:])), "Capture PTS missing, duplicated or non-monotonic")
    require(abs(times[0] - case["captureStartedMs"]) < 3000, "Capture PTS are not absolute wallclock: correlation unavailable")
    first = command(["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1", "-threads", "1", "-f", "image2pipe", "-c:v", "ppm", "pipe:1"])
    width, height, pixels = ppm_image(first)
    require((width, height) == (1280, 800), "Unexpected recording dimensions")
    roi = locate_strip(width, height, pixels, roi_index)
    crop = f"crop={roi['width']}:{roi['height']}:{roi['x']}:{roi['y']}"
    raw = command(["ffmpeg", "-v", "error", "-i", str(video), "-vf", crop, "-fps_mode", "passthrough", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    size = roi["width"] * roi["height"] * 3
    require(len(raw) == len(times) * size, "Decoded frame count differs from timestamp count")
    samples = []
    for i, epoch in enumerate(times):
        frame = raw[i * size:(i + 1) * size]
        cyan_height, follower = stripe_geometry(frame)
        samples.append({"index": i, "epochMs": epoch, "cyanHeight": cyan_height, "followerY": follower, "sha256": hashlib.sha256(frame).hexdigest()})
    sample_name = "pixel-samples-grid.json" if roi_index else "pixel-samples.json"
    (directory / sample_name).write_text(json.dumps({"roi": roi, "samples": samples}, indent=2) + "\n")
    require(samples[0]["cyanHeight"] == 24, "Initial captured panel is not 24px")
    require(abs(samples[-1]["cyanHeight"] - 264) <= 1, "Final captured panel is not 264px: wrong/stale surface")
    block = case["block"]
    start, end = block["start"]["epochMs"], block["end"]["epochMs"]
    perf_delta = block["end"]["perfMs"] - block["start"]["perfMs"]
    require(abs((end - start) - perf_delta) <= 50, "Wallclock changed relative to monotonic block clock")
    require(end - start >= case["ms"] - 2, "Busy block shorter than requested")
    require(block["heartbeatBefore"] == block["heartbeatAfter"], "Main JS callback executed inside busy loop")
    # Save actual externally captured full frames at known PTS, not screenshots requested during block.
    points = {"pre": times[0], "early": start + 400, "middle": (start + end) / 2, "late": end - 400, "post": times[-1]}
    indices = {}
    for name, epoch in points.items():
        index = min(range(len(times)), key=lambda i: abs(times[i] - epoch))
        indices[name] = {"frame": index, "epochMs": times[index]}
        command(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{index})", "-frames:v", "1", "-threads", "1", str(directory / f"capture-{name}.png")])
    (directory / "screenshots.json").write_text(json.dumps(indices, indent=2) + "\n")
    return {"roi": roi, **pixel_verdict(samples, start, end, case["mode"])}


def durations(events):
    """Normalize complete and synchronous begin/end slices; never pair across TIDs."""
    stacks = defaultdict(list)
    for event in events:
        phase = event.get("ph")
        key = (event.get("pid"), event.get("tid"))
        if phase == "X":
            yield event
        elif phase == "B":
            stacks[key].append(event)
        elif phase == "E" and stacks[key]:
            begin = stacks[key].pop()
            yield {**begin, "ph": "X", "dur": event["ts"] - begin["ts"]}


def trace_evidence(events, mode, thread_pattern, event_pattern, requested_ms):
    names = {(event.get("pid"), event.get("tid")): event.get("args", {}).get("name", "") for event in events if event.get("ph") == "M" and event.get("name") == "thread_name"}
    marks = {}
    for name in ["mutation", "block-start", "block-end"]:
        found = [event for event in events if event.get("name") == f"validation:{name}" and "ts" in event and "blink.user_timing" in event.get("cat", "")]
        require(len(found) == 1, f"Trace milestone missing/ambiguous: {name}")
        marks[name] = found[0]
    start, end = marks["block-start"], marks["block-end"]
    main = (start["pid"], start["tid"])
    require(main == (end["pid"], end["tid"]) == (marks["mutation"]["pid"], marks["mutation"]["tid"]), "Block markers moved between threads")
    require("CrRendererMain" in names.get(main, ""), f"Block is not on named renderer main thread: {main}/{names.get(main)}")
    require(0 <= start["ts"] - marks["mutation"]["ts"] < 100000, "Class mutation not immediately before block")
    require(end["ts"] - start["ts"] >= (requested_ms - 2) * 1000, "Trace busy interval too short")
    slices = list(durations(events))
    enclosing = [event for event in slices if (event.get("pid"), event.get("tid")) == main and event["ts"] <= marks["mutation"]["ts"] and event["ts"] + event.get("dur", 0) >= end["ts"]]
    require(enclosing, "No main-thread synchronous trace slice encloses mutation AND busy block")
    lower, upper = start["ts"] + GUARD_MS * 1000, end["ts"] - GUARD_MS * 1000
    render_threads = {key for key, name in names.items() if key[0] == main[0] and key != main and re.search(thread_pattern, name) and not re.search(r"Compositor|Viz|GPU|Raster", name, re.I)}
    render = [event for event in events if (event.get("pid"), event.get("tid")) in render_threads and lower <= event.get("ts", -1) <= upper and event.get("ph") in ("X", "B", "I", "i") and re.search(event_pattern, event.get("name", ""))]
    groups = defaultdict(list)
    for event in render:
        groups[(event["pid"], event["tid"])].append(event)
    summaries = []
    for key, group in groups.items():
        timestamps = sorted({event["ts"] for event in group})
        summaries.append({"pid": key[0], "tid": key[1], "threadName": names[key], "events": len(group), "distinctTimestamps": len(timestamps), "spanMs": (timestamps[-1] - timestamps[0]) / 1000, "eventNames": dict(Counter(event["name"] for event in group))})
    if mode == "omt":
        require(any(group["distinctTimestamps"] >= MIN_CHANGES and group["spanMs"] >= MIN_SPAN_MS and group["eventNames"].get("ReplicaPage::Paint", 0) >= MIN_CHANGES and group["eventNames"].get("ReplicaPage::BeginFrame", 0) >= MIN_CHANGES for group in summaries), "No sustained OMT BeginFrame + Paint events on a non-main renderer thread during busy block")
    else:
        require(not render, "Flag-off baseline unexpectedly emitted OMT render events")
    return {"main": {"pid": main[0], "tid": main[1], "threadName": names[main]}, "blockTraceUs": [start["ts"], end["ts"]], "enclosingMainSlices": [{key: event.get(key) for key in ("name", "cat", "ts", "dur", "pid", "tid")} for event in enclosing], "renderThreads": summaries, "threadInventory": [{"pid": key[0], "tid": key[1], "name": name} for key, name in sorted(names.items())]}


def analyze_trace(directory, case, run):
    complete = load(directory / "trace-complete.json")
    require(not complete.get("dataLossOccurred", True), "Missing/lost trace data")
    events = trace_events(directory)
    # Keep inventory even when strict event-name matching fails.
    inventory = [event for event in events if event.get("name") == "thread_name" or re.search(r"OMT|OffMainThread|ReplicaPage::|RenderThreadJournal::(BeginHandBack|HandBack|AnimationTimingsAdopted|Unreplicable)", event.get("name", ""), re.I)]
    (directory / "trace-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    result = trace_evidence(events, case["mode"], run["traceThread"], run["traceEvent"], case["ms"])
    trace_ms = (result["blockTraceUs"][1] - result["blockTraceUs"][0]) / 1000
    page_ms = case["block"]["end"]["perfMs"] - case["block"]["start"]["perfMs"]
    require(abs(trace_ms - page_ms) <= 50, "Trace and page block intervals disagree")
    return result


def image_roi(path, rect):
    crop = f"crop={rect['width']}:{rect['height']}:{rect['x']}:{rect['y']}"
    pixels = command(["ffmpeg", "-v", "error", "-i", str(path), "-vf", crop, "-frames:v", "1", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    require(len(pixels) == rect["width"] * rect["height"] * 3, "Smoke screenshot crop clipped")
    return hashlib.sha256(pixels).hexdigest()


def image_alignment(cdp, x11):
    offsets = []
    for image in (cdp, x11):
        ppm = command(["ffmpeg", "-v", "error", "-i", str(image), "-frames:v", "1", "-threads", "1", "-f", "image2pipe", "-c:v", "ppm", "pipe:1"])
        offsets.append(locate_strip(*ppm_image(ppm)))
    return {axis: offsets[1][axis] - offsets[0][axis] for axis in ("x", "y")}


def smoke_pixels(directory, steps):
    offset = image_alignment(directory / "smoke-before-cdp.png", directory / "smoke-before-x11.png")
    delta_x, delta_y = offset["x"], offset["y"]
    results = []
    previous = "smoke-before"
    for step in steps:
        name = step["name"]
        for source in ("cdp", "x11"):
            rect = dict(step["rect"])
            if source == "x11":
                rect["x"] += delta_x
                rect["y"] += delta_y
            before = image_roi(directory / f"{previous}-{source}.png", rect)
            after = image_roi(directory / f"{name}-{source}.png", rect)
            require(before != after, f"{name}: no {source} pixels changed in target ROI")
            results.append({"step": name, "source": source, "rect": rect, "beforeSha256": before, "afterSha256": after})
        previous = name
    (directory / "smoke-pixels.json").write_text(json.dumps(results, indent=2) + "\n")


def analyze_run(output):
    from extended_analysis import analyze_fallbacks, analyze_handoff, analyze_queries, compare_extended, compare_memory, gpu_evidence, lifecycle_evidence, memory_evidence, smoke_trace_evidence, validate_input, validate_unreplicable
    run = load(output / "run.json")
    extended = run.get("schemaVersion", 1) >= 2
    hybrid = run.get("schemaVersion", 1) >= 3
    kinds = ("height", "grid", "queries") if extended else ("height", "grid")
    capture = run.get("capture", {"kind": "xvfb", "fps": 30})
    real_display = capture["kind"] == "display"
    limits = f"Real X display {run.get('display')} (GPU, compositing window manager), {capture['fps']} fps x11grab of the harness window; not physical scanout timing or cross-platform correctness." if real_display else "Xvfb software-display validation, not physical GPU scanout/FPS or cross-platform correctness."
    report = {"passed": False, "failures": list(run.get("failures", [])), "cases": [], "capture": capture, "limits": limits + " CDP smoke screenshots are not block evidence."}
    expected = {(mode, kind, ms) for mode in ("baseline", "omt") for kind in kinds for ms in (3000, 10000)}
    actual = [(case["mode"], case["kind"], case["ms"]) for case in run["cases"]]
    if set(actual) != expected or len(actual) != len(expected):
        report["failures"].append(f"Missing/duplicate required cases: need baseline + omt, {kinds}, 3s + 10s")
    for case in run["cases"]:
        directory = output / case["mode"] / f"{case['kind']}-{case['ms']}"
        entry = {"mode": case["mode"], "kind": case["kind"], "ms": case["ms"], "failures": []}
        if not case.get("completed"):
            entry["failures"].append("Harness milestones incomplete")
        def pixels():
            result = analyze_pixels(directory, case)
            if case["kind"] == "queries":
                grid = analyze_pixels(directory, case, 1)
                result = {**result, "panels": {"height": result, "grid": grid}, "heightRangePx": min(result["heightRangePx"], grid["heightRangePx"]), "heightChangeSteps": min(result["heightChangeSteps"], grid["heightChangeSteps"])}
            return result
        analyses = [("pixels", pixels), ("trace", lambda: analyze_trace(directory, case, run))]
        if extended:
            analyses.append(("fallbacks", lambda: analyze_fallbacks(directory, case, run)))
        if hybrid:
            analyses.append(("handoff", lambda: analyze_handoff(directory, case)))
        if case["kind"] == "queries":
            analyses.append(("queries", lambda: analyze_queries(directory, case)))
        for label, function in analyses:
            try:
                entry[label] = function()
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
                entry["failures"].append(f"{label}: {error}")
        entry["passed"] = not entry["failures"]
        report["cases"].append(entry)
    for mode in ("baseline", "omt"):
        try:
            directory = output / mode
            version = load(directory / "version.json")
            require(version["binarySha256"] == run["binarySha256"], "Binary hash mismatch")
            require(version["product"].endswith("/153.0.8010.55"), "Wrong version")
            steps = load(directory / "smoke.json")
            require([step["name"] for step in steps] == [f"smoke-{step}" for step in ("insert", "remove", "text", "inline", "cssom-insert", "cssom-delete")], "Smoke milestones incomplete")
            smoke_pixels(directory, steps)
            require(load(directory / "lifecycle.json")["navigationReturned"], "Navigation milestone missing")
            require(not load(directory / "fatal-lines.json"), "Fatal Chromium log signatures")
            log = (directory / "chrome.log").read_text(errors="replace")
            omt_lines = [line for line in log.splitlines() if "[OMT]" in line]
            (directory / "omt-lines.log").write_text("\n".join(omt_lines) + "\n")
            if mode == "omt":
                require(omt_lines, "Enabled run missing [OMT] instrumentation milestone")
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
            report["failures"].append(f"{mode}: {error}")
    if extended:
        checks = [("native-input", validate_input), ("page-threads", lifecycle_evidence)]
        if hybrid:
            checks += [("smoke-trace", smoke_trace_evidence), ("memory", memory_evidence), ("unreplicable", lambda directory, mode: validate_unreplicable(directory) if mode == "omt" else None)]
        if real_display:
            checks.append(("gpu", lambda directory, mode: gpu_evidence(directory, mode, run)))
        for mode in ("baseline", "omt"):
            for name, check in checks:
                try:
                    report.setdefault("extended", {}).setdefault(mode, {})[name] = check(output / mode, mode)
                except (OSError, ValueError, KeyError, RuntimeError) as error:
                    report["failures"].append(f"{mode}/{name}: {error}")
        try:
            report["comparisons"] = compare_extended(output, run["cases"])
        except (OSError, ValueError, KeyError) as error:
            report["failures"].append(f"baseline comparison: {error}")
        if hybrid:
            memory = {mode: report.get("extended", {}).get(mode, {}).get("memory") for mode in ("baseline", "omt")}
            try:
                require(all(memory.values()), "memory evidence missing for a mode")
                report["memory"] = compare_memory(memory["baseline"], memory["omt"])
            except ValueError as error:
                report["failures"].append(f"memory comparison: {error}")
    # Explicit paired differential, not merely independent successful runs.
    pairs = []
    for kind in kinds:
        for ms in (3000, 10000):
            matched = {entry["mode"]: entry for entry in report["cases"] if entry["kind"] == kind and entry["ms"] == ms}
            baseline = matched.get("baseline", {}).get("pixels", {})
            omt = matched.get("omt", {}).get("pixels", {})
            delta = omt.get("heightRangePx", 0) - baseline.get("heightRangePx", 0)
            pairs.append({"kind": kind, "ms": ms, "omtMinusBaselineHeightRangePx": delta})
            if delta < 29:
                report["failures"].append(f"{kind}/{ms}: missing OMT-versus-baseline differential")
    report["pairs"] = pairs
    report["passed"] = not report["failures"] and len(report["cases"]) == len(expected) and all(entry["passed"] for entry in report["cases"])
    lines = ["# OMT validation", "", f"**{'PASS' if report['passed'] else 'FAIL'}**", "", "| Mode | Layout | Block | Pixel change steps | Height range | Render PID/TID | TakeOver after start | HandBack after end | Result |", "|---|---|---:|---:|---:|---|---:|---:|---|"]
    for entry in report["cases"]:
        pixels = entry.get("pixels", {})
        threads = entry.get("trace", {}).get("renderThreads", [])
        tids = ", ".join(f"{thread['pid']}/{thread['tid']}" for thread in threads) or "—"
        handoff = entry.get("handoff", {})
        takeover = f"{handoff['takeoverLatencyMs']:.1f}ms" if "takeoverLatencyMs" in handoff else "—"
        handback = f"{handoff['handBackAfterEndMs']:.1f}ms" if "handBackAfterEndMs" in handoff else "—"
        lines.append(f"| {entry['mode']} | {entry['kind']} | {entry['ms']}ms | {pixels.get('heightChangeSteps', '—')} | {pixels.get('heightRangePx', '—')}px | {tids} | {takeover} | {handback} | {'PASS' if entry['passed'] else 'FAIL'} |")
        for failure in entry["failures"]:
            report["failures"].append(f"{entry['mode']}/{entry['kind']}/{entry['ms']}: {failure}")
    if extended:
        lines += ["", "## Main-thread lifecycle entries (conservative unthrottled fallback counts)", "", "SkippedForFocus is informational: skipped work is counted separately, never subtracted from fallbacks.", "", "| Mode/case | Before block | During block | After block | SkippedForFocus before/during/after |", "|---|---:|---:|---:|---|"]
        for case in run["cases"]:
            fallback_file = output / case["mode"] / f"{case['kind']}-{case['ms']}" / "fallbacks.json"
            if fallback_file.exists():
                evidence = load(fallback_file)
                counts = evidence["traceCounts"]
                skipped = evidence.get("skippedForFocus", {}).get("traceCounts", {})
                skipped_text = "/".join(str(skipped.get(window, "—")) for window in ("before", "during", "after"))
                lines.append(f"| {case['mode']}/{case['kind']}/{case['ms']} | {counts['before']} | {counts['during']} | {counts['after']} | {skipped_text} |")
        lines += ["", "## BFCache restoration", "", "| Mode | Render thread counts | pageshow.persisted | X11 heights A/B/restored/fresh | Fresh replica | Fresh Paints |", "|---|---|---|---|---|---|"]
        for mode in ("baseline", "omt"):
            life = report.get("extended", {}).get(mode, {}).get("page-threads")
            if not life:
                lines.append(f"| {mode} | FAIL / incomplete | — | — | — | — |")
                continue
            counts = " → ".join(str(len(stage["renderThreads"])) for stage in life["stages"])
            cached = life["bfcache"]
            heights = "/".join(str(cached["pixels"]["frames"][name]["cyanHeight"]) for name in ("owner-a", "owner-b", "restored-a", "restored-mutated-a"))
            replica = life["replicaIdsByStage"][-1][0] if mode == "omt" else "none"
            lines.append(f"| {mode} | {counts} | {cached['pageshow']['persisted']} | {heights}px | {replica} | {cached.get('freshPaints', 'n/a')} |")
    if hybrid:
        number = lambda value, unit: "—" if value is None else f"{value:.1f}{unit}"
        lines += ["", "## Memory (medians)", "", "| Mode | Renderer churn 5–10s | Renderer churn last 5s | Renderer idle last 10s | TakeOvers during churn | GPU process PSS churn/idle | GPU process VRAM churn/idle |", "|---|---:|---:|---:|---:|---:|---:|"]
        for mode in ("baseline", "omt"):
            memory = report.get("extended", {}).get(mode, {}).get("memory")
            gpu = (memory or {}).get("gpuProcess", {})
            lines.append(f"| {mode} | {memory['warmChurnMedianMb']:.1f}MB | {memory['lastChurnMedianMb']:.1f}MB | {memory['idleMedianMb']:.1f}MB | {memory['takeoversDuringChurn']} | {number(gpu.get('churnPssMb'), 'MB')} / {number(gpu.get('idlePssMb'), 'MB')} | {number(gpu.get('churnVramMib'), 'MiB')} / {number(gpu.get('idleVramMib'), 'MiB')} |" if memory else f"| {mode} | FAIL / incomplete | — | — | — | — | — |")
    lines += ["", "## Display / capture", "", f"- Capture: {capture['kind']} {run.get('display')}, {capture['fps']} fps requested"]
    if real_display:
        gpu_info = run.get("gpu", {})
        lines.append(f"- nvidia-smi: {gpu_info.get('nvidiaSmi')}")
        lines.append(f"- DPMS: before {run.get('dpms', {}).get('before')}, during {run.get('dpms', {}).get('during')}, after {run.get('dpms', {}).get('after')}, restored={run.get('dpms', {}).get('restored')}")
        for mode in ("baseline", "omt"):
            evidence = report.get("extended", {}).get(mode, {}).get("gpu")
            window = gpu_info.get(mode, {}).get("window", {})
            lines.append(f"- {mode}: {evidence['glRenderer']} ({evidence['glImplementationParts']}), features {evidence['featureStatus']}, raster providers {evidence['rasterProviders']}, window origin {window.get('origin')}" if evidence else f"- {mode}: GPU evidence FAIL / incomplete")
    lines += ["", "## Failures", *[f"- {failure}" for failure in report["failures"]], "", "## Interpretation", "", report["limits"], "", "See pixel-samples.json for absolute capture timestamps and external ROI hashes; trace-inventory.json and trace.json for thread attribution. Frame counts here are captured samples, never document timeline / JS animation counts."]
    (output / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        passed = analyze_run(args.output.resolve())
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: analysis could not complete: {error}")
        passed = False
    raise SystemExit(0 if passed else 1)
