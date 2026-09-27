import copy
import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extended_analysis import (
    FALLBACK_EVENT,
    SKIPPED_FOCUS_EVENT,
    QUERY_TYPES,
    analyze_fallbacks,
    compare_extended,
    compare_memory,
    handoff_evidence,
    memory_evidence,
    smoke_trace_evidence,
    validate_unreplicable,
    fallback_evidence,
    lifecycle_evidence,
    lifecycle_pixel_verdict,
    log_records,
    outside_fallbacks,
    query_roundtrips,
    query_samples,
    window_scroll_restore,
)
from test_validation import trace_fixture


EPOCH = int(datetime.datetime(2026, 9, 26, 15, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def samples_fixture(changing=True):
    samples = []
    for t in range(0, 3001, 200):
        value = 24 + min(240, t / 10) if changing else 24
        samples.append({"t": t, "height": {"offset": value, "rect": value, "computed": value}, "grid": {"offset": value, "rect": value, "computed": value}})
    return {"ms": 3000, "samples": samples, "heartbeatBefore": 1, "heartbeatAfter": 1, "assertions": {"checks": [{"name": str(i), "actual": 1, "expected": 1, "passed": True} for i in range(50)], "outsideShadow": {"element": "hit-probe", "elements": ["hit-probe"]}}}


def roundtrip_fixture():
    events = trace_fixture()
    events += [
        {"name": "RenderThread::RunQuery", "ph": "X", "ts": 1500000, "dur": 1000, "pid": 11, "tid": 12, "args": {"type": 7}},
        {"name": "ReplicaPage::AnswerQuery", "ph": "X", "ts": 1500100, "dur": 500, "pid": 11, "tid": 13, "args": {"type": 7}},
    ]
    return events


def roundtrip_check(events, mode="omt"):
    return query_roundtrips(events, {"ts": 1000000, "pid": 11, "tid": 12}, {"ts": 4000000}, mode)


def log_line(tid, ms, text):
    date = datetime.datetime.fromtimestamp((EPOCH + ms) / 1000, datetime.timezone.utc)
    return f"[11:{tid}:{date.strftime('%m%d/%H%M%S.%f')}:INFO:file.cc:1] [OMT] {text}\n"


def write_lifecycle(directory, mode="omt"):
    folder = directory / "page-threads"
    folder.mkdir()
    names = {12: "CrRendererMain", 13: "BlinkRenderThread", 14: "BlinkRenderThread", 15: "BlinkRenderThread", 16: "BlinkRenderThread"}
    events = [{"ph": "M", "name": "thread_name", "pid": 11, "tid": tid, "args": {"name": name}} for tid, name in names.items() if mode == "omt" or tid == 12]
    for name, ts in (("page-a", 300000), ("page-peer", 900000), ("page-b", 1800000), ("page-a-restored", 2400000), ("restored-mutation", 2600000), ("restored-block-end", 3200000), ("history-back-end", 3400000)):
        events.append({"name": f"validation:{name}", "cat": "blink.user_timing", "ph": "R", "pid": 11, "tid": 12, "ts": ts})
    if mode == "omt":
        events.append({"name": "ReplicaPage::TakeOver", "cat": "blink", "ph": "I", "pid": 11, "tid": 16, "ts": 2650000, "args": {"main_task_ms": 50}})
        for ts, kind in ((2750000, 3), (2760000, 13), (2900000, 3), (2910000, 13)):
            events += [{"name": "RenderThread::RunQuery", "ph": "X", "pid": 11, "tid": 12, "ts": ts, "dur": 100, "args": {"type": kind}}, {"name": "ReplicaPage::AnswerQuery", "ph": "X", "pid": 11, "tid": 16, "ts": ts + 20, "dur": 40, "args": {"type": kind}}]
        events.append({"name": "ReplicaPage::Paint", "ph": "X", "pid": 11, "tid": 16, "ts": 2700000, "dur": 100})
    (folder / "trace.json").write_text(json.dumps({"traceEvents": events}))
    (folder / "trace-complete.json").write_text(json.dumps({"dataLossOccurred": False}))
    thread = lambda tid: {"pid": 11, "tid": tid, "comm": "BlinkRenderThread"[:15], "startTicks": str(tid * 100)}
    stages = [
        {"name": "one-page", "epochMs": EPOCH + 400, "renderThreads": [thread(13)]},
        {"name": "two-pages", "epochMs": EPOCH + 1000, "renderThreads": [thread(13), thread(14)]},
        {"name": "peer-closed", "epochMs": EPOCH + 1500, "renderThreads": [thread(13)]},
        {"name": "owner-navigated", "epochMs": EPOCH + 1900, "renderThreads": [thread(15)]},
        {"name": "owner-restored", "epochMs": EPOCH + 2500, "renderThreads": [thread(16)]},
    ]
    if mode == "baseline":
        for stage in stages:
            stage["renderThreads"] = []
    logs = ""
    for replica, tid, ms, url in [(1, 13, 100, "url-a"), (2, 14, 600, "url-peer"), (3, 15, 1700, "url-b"), (4, 16, 2300, "url-a")]:
        logs += log_line(12, ms, f"render thread started for replica {replica}")
        logs += log_line(12, ms, f'render thread journal attached to "{url}"')
        logs += log_line(tid, ms, f"replica {replica} created on render thread, gpu=0")
    logs += log_line(12, 1200, "render thread stopped") + log_line(12, 1650, "render thread stopped") + log_line(12, 1651, "page entered the back/forward cache; render thread stopped") + log_line(12, 2200, "render thread stopped")
    if mode == "baseline":
        logs = ""
    (directory / "chrome.log").write_text(logs)
    result = {"completed": True, "startedMs": EPOCH, "logStart": 0, "logEnd": len(logs), "stages": stages, "urlA": "url-a", "urlPeer": "url-peer", "urlB": "url-b", "peerCloseStartedMs": EPOCH + 1100, "navigationStartedMs": EPOCH + 1600, "historyBackStartedMs": EPOCH + 2100, "bfcache": {"expectedToken": "sentinel", "pageshow": {"persisted": True, "url": "url-a"}, "original": {"height": 64, "token": "sentinel"}, "onB": {"height": 24, "token": None}, "restored": {"height": 64, "token": "sentinel"}, "mutated": {"height": 96, "token": "sentinel"}}}
    (folder / "threads.json").write_text(json.dumps(result))
    return result


class ExtendedTests(unittest.TestCase):
    def setUp(self):
        pixels = patch("extended_analysis.lifecycle_pixels", return_value={"fixture": True})
        pixels.start()
        self.addCleanup(pixels.stop)

    def test_skipped_focus_is_informational_and_never_cancels_fallback(self):
        events = [{"name": SKIPPED_FOCUS_EVENT, "ph": "I", "ts": ts, "args": {"reason": 13}} for ts in (99, 150, 201)]
        result = fallback_evidence(events, [], {"ts": 100}, {"ts": 200}, 100, 200)
        self.assertEqual(result["skippedForFocus"]["traceCounts"], {"before": 1, "during": 1, "after": 1})
        self.assertEqual(result["traceCounts"], {"before": 0, "during": 0, "after": 0})
        self.assertTrue(result["zeroDuringBlock"])
        events.append({"name": FALLBACK_EVENT, "ph": "I", "ts": 160})
        result = fallback_evidence(events, [], {"ts": 100}, {"ts": 200}, 100, 200)
        self.assertEqual(result["traceCounts"]["during"], 1)
        self.assertFalse(result["zeroDuringBlock"])

    def test_outside_focus_skips_reported_separately(self):
        events = [{"name": name, "ph": "I", "ts": 100} for name in (SKIPPED_FOCUS_EVENT, FALLBACK_EVENT)]
        result = outside_fallbacks(events, [])
        self.assertEqual(result["unthrottledTraceCount"], 1)
        self.assertEqual(result["skippedForFocus"]["unthrottledTraceCount"], 1)

    def test_scope_observations_do_not_add_or_relax_query_gates(self):
        block = samples_fixture()
        block["scope"] = {"computedStyleEnumeration": {"required": False, "excludedMembers": ["cssText", "length"]}}
        self.assertEqual(query_samples(block, "omt")["scopeObservations"], block["scope"])
        block["assertions"]["checks"][0]["passed"] = False
        with self.assertRaisesRegex(ValueError, "mismatches"):
            query_samples(block, "omt")

    def test_incomplete_native_comparison_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            cases = []
            for mode in ("baseline", "omt"):
                folder = output / mode / "input"
                folder.mkdir(parents=True)
                (folder / "input.json").write_text(json.dumps({"completed": False}))
                for ms in (3000, 10000):
                    cases.append({"mode": mode, "ms": ms, "kind": "queries", "block": samples_fixture()})
            with self.assertRaisesRegex(ValueError, "Input comparison missing events"):
                compare_extended(output, cases)

    def test_window_query_enum_contract(self):
        self.assertEqual([QUERY_TYPES[name] for name in ("InnerWidth", "InnerHeight", "WindowScrollX", "WindowScrollY")], [24, 25, 26, 27])

    def test_window_scroll_restore_before_pixel_guard(self):
        block = samples_fixture()
        block["scope"] = {"windowScroll": {"required": True, "restoredAtMs": 30}}
        query_samples(block, "omt")
        for invalid in (None, -1, 250, 400, float("nan"), float("inf")):
            with self.subTest(restoredAtMs=invalid):
                block["scope"]["windowScroll"]["restoredAtMs"] = invalid
                with self.assertRaisesRegex(ValueError, "guarded pixel"):
                    query_samples(block, "omt")

    def test_window_scroll_trace_requires_correct_thread_and_guard(self):
        start, end = {"pid": 11, "tid": 12, "ts": 1000000}, {"ts": 4000000}
        event = {"name": "validation:window-scroll-restored", "cat": "blink.user_timing", "ph": "R", "pid": 11, "tid": 12, "ts": 1030000}
        self.assertEqual(window_scroll_restore([event], start, end)["restoredAtMs"], 30)
        for change in ({"pid": 99}, {"tid": 13}, {"ts": 999999}, {"ts": 1250000}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, "restoration trace"):
                    window_scroll_restore([{**event, **change}], start, end)
        with self.assertRaisesRegex(ValueError, "Missing/ambiguous"):
            window_scroll_restore([], start, end)

    def test_query_growth_and_baseline_frozen_values(self):
        self.assertEqual(query_samples(samples_fixture(), "omt")["samples"], 16)
        query_samples(samples_fixture(False), "baseline")

    def test_query_freeze_fails_omt(self):
        with self.assertRaises(ValueError):
            query_samples(samples_fixture(False), "omt")

    def test_query_plateau_during_transition_fails(self):
        block = samples_fixture()
        block["samples"][4]["height"] = dict(block["samples"][3]["height"])
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            query_samples(block, "omt")

    def test_query_wrong_exact_geometry_fails(self):
        block = samples_fixture()
        block["assertions"]["checks"][0]["actual"] = 999
        with self.assertRaisesRegex(ValueError, "mismatches"):
            query_samples(block, "baseline")

    def test_query_final_size_required_inside_task(self):
        block = samples_fixture()
        block["samples"][-1]["grid"] = {"offset": 260, "rect": 260, "computed": 260}
        with self.assertRaisesRegex(ValueError, "final query"):
            query_samples(block, "omt")

    def test_query_gap_fails(self):
        block = samples_fixture()
        block["samples"][5]["t"] += 500
        with self.assertRaisesRegex(ValueError, "stalled"):
            query_samples(block, "omt")

    def test_roundtrip_same_type_inside_main_wait(self):
        self.assertEqual(roundtrip_check(roundtrip_fixture())["answers"], 1)
        roundtrip_check(trace_fixture(False), "baseline")

    def test_roundtrip_adjacent_same_type_queries_are_not_ambiguous(self):
        events = roundtrip_fixture()
        events += [
            {"name": "RenderThread::RunQuery", "ph": "X", "ts": 1501001, "dur": 20, "pid": 11, "tid": 12, "args": {"type": 7}},
            {"name": "ReplicaPage::AnswerQuery", "ph": "X", "ts": 1501005, "dur": 3, "pid": 11, "tid": 13, "args": {"type": 7}},
        ]
        self.assertEqual(roundtrip_check(events)["answers"], 2)

    def test_roundtrip_answer_one_microsecond_past_wait_fails(self):
        events = roundtrip_fixture()
        events[-1]["dur"] = 901
        with self.assertRaisesRegex(ValueError, "enclose"):
            roundtrip_check(events)

    def test_roundtrip_outside_main_wait_fails(self):
        events = roundtrip_fixture()
        events[-1]["ts"] += 2000
        with self.assertRaisesRegex(ValueError, "enclose"):
            roundtrip_check(events)

    def test_roundtrip_compositor_fails(self):
        events = roundtrip_fixture()
        events[1]["args"]["name"] = "Compositor"
        with self.assertRaisesRegex(ValueError, "enclose"):
            roundtrip_check(events)

    def test_roundtrip_wrong_type_fails(self):
        events = roundtrip_fixture()
        events[-1]["args"]["type"] = 99
        with self.assertRaisesRegex(ValueError, "enclose"):
            roundtrip_check(events)

    def test_baseline_query_forwarding_fails(self):
        with self.assertRaisesRegex(ValueError, "Baseline"):
            roundtrip_check(roundtrip_fixture(), "baseline")

    def test_log_utc_timestamp_and_counter(self):
        records = log_records(log_line(12, 123, "main-thread style fallback #100 (reason 4)"), EPOCH)
        self.assertAlmostEqual(records[0]["epochMs"], EPOCH + 123, places=2)
        self.assertEqual(records[0]["pid"], 11)
        self.assertEqual(records[0]["tid"], 12)

    def test_fallback_trace_catches_unlogged_occurrence(self):
        events = [{"name": FALLBACK_EVENT, "ph": "I", "ts": 101, "args": {"count": 11}}]
        result = fallback_evidence(events, [], {"ts": 100}, {"ts": 200}, EPOCH, EPOCH + 100)
        self.assertFalse(result["zeroDuringBlock"])
        self.assertEqual(result["traceCounts"]["during"], 1)

    def test_confirmed_instant_entry_counts_even_without_work_measurement(self):
        args = {"phase": "style", "reason": 0, "count": 1}
        events = [{"name": FALLBACK_EVENT, "cat": "blink", "ph": "I", "pid": 11, "tid": 12, "ts": 150, "args": args}]
        result = fallback_evidence(events, [], {"ts": 100}, {"ts": 200}, EPOCH, EPOCH + 100)
        self.assertFalse(result["zeroDuringBlock"])
        self.assertEqual(result["traceCounts"]["during"], 1)
        self.assertEqual(result["traceOccurrences"][0]["args"], args)

    def test_fallback_outside_block_is_reported_not_failed(self):
        events = [{"name": FALLBACK_EVENT, "ph": "I", "ts": ts} for ts in (90, 210)]
        result = fallback_evidence(events, [], {"ts": 100}, {"ts": 200}, EPOCH, EPOCH + 100)
        self.assertTrue(result["zeroDuringBlock"])
        self.assertEqual(result["traceCounts"], {"before": 1, "during": 0, "after": 1})

    def test_fallback_missing_log_timestamp_fails(self):
        records = log_records("[OMT] main-thread layout fallback #12 (reason 3)", EPOCH)
        result = fallback_evidence([], records, {"ts": 0}, {"ts": 100}, EPOCH, EPOCH + 100)
        self.assertFalse(result["zeroDuringBlock"])

    def test_fallback_log_counters_are_not_event_counts(self):
        records = log_records(log_line(12, 20, "main-thread style fallback #100 (reason 4)"), EPOCH)
        result = fallback_evidence([], records, {"ts": 0}, {"ts": 100}, EPOCH, EPOCH + 100)
        self.assertEqual(result["loggedCounts"]["during"], 1)
        self.assertEqual(result["loggedFallbacks"][0]["counter"], 100)
        self.assertFalse(result["zeroDuringBlock"])

    def test_fallback_throttled_logs_cannot_prove_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            directory = parent / "case"
            directory.mkdir()
            (parent / "chrome.log").write_text("")
            (directory / "trace.json").write_text(json.dumps({"traceEvents": trace_fixture(False)}))
            (directory / "trace-complete.json").write_text(json.dumps({"dataLossOccurred": False}))
            case = {"logStart": 0, "logEnd": 0, "startedMs": EPOCH, "block": {"start": {"epochMs": EPOCH}, "end": {"epochMs": EPOCH + 3000}}}
            with self.assertRaisesRegex(ValueError, "not confirmed"):
                analyze_fallbacks(directory, case, {})
            self.assertTrue((directory / "fallbacks.json").exists())
            analyze_fallbacks(directory, case, {"fallbackTraceEvent": FALLBACK_EVENT})

    def test_lifecycle_per_page_tids_replica_ids_and_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory)
            result = lifecycle_evidence(directory, "omt")
            self.assertEqual(result["replicaIdsByStage"], [[1], [1, 2], [3], [4]])
            self.assertEqual(result["bfcache"]["freshPaints"], 1)

    def test_bfcache_restored_takeover_required_on_new_thread(self):
        for change, message in (({"ts": 3300000}, "exactly one"), ({"tid": 13}, "not on the new render thread")):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                write_lifecycle(directory)
                trace = directory / "page-threads/trace.json"
                value = json.loads(trace.read_text())
                for event in value["traceEvents"]:
                    if event["name"] == "ReplicaPage::TakeOver":
                        event.update(change)
                trace.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, message):
                    lifecycle_evidence(directory, "omt")

    def test_lifecycle_baseline_with_handoff_events_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory, "baseline")
            trace = directory / "page-threads/trace.json"
            value = json.loads(trace.read_text())
            value["traceEvents"].append({"name": "RenderThreadJournal::HandBack", "ph": "I", "pid": 11, "tid": 12, "ts": 3000000})
            trace.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "hand-off"):
                lifecycle_evidence(directory, "baseline")

    def test_lifecycle_baseline_has_no_render_threads_or_queries(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory, "baseline")
            result = lifecycle_evidence(directory, "baseline")
            self.assertEqual([len(stage["renderThreads"]) for stage in result["stages"]], [0] * 5)
            self.assertEqual(result["bfcache"]["roundtrips"]["requests"], 0)

    def test_bfcache_missing_cache_hit_geometry_or_token_fails(self):
        for field, value, message in (("pageshow", {"persisted": False, "url": "url-a"}, "BFCache hit"), ("restored", {"height": 24, "token": "sentinel"}, "geometry"), ("restored", {"height": 64, "token": "lost"}, "DOM identity")):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                result = write_lifecycle(directory)
                result["bfcache"][field] = value
                (directory / "page-threads/threads.json").write_text(json.dumps(result))
                with self.assertRaisesRegex(ValueError, message):
                    lifecycle_evidence(directory, "omt")

    def test_bfcache_old_thread_reused_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = write_lifecycle(directory)
            result["stages"][4]["renderThreads"] = copy.deepcopy(result["stages"][0]["renderThreads"])
            (directory / "page-threads/threads.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "reused a stopped"):
                lifecycle_evidence(directory, "omt")

    def test_bfcache_old_replica_reused_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory)
            log = directory / "chrome.log"
            log.write_text(log.read_text().replace("replica 4", "replica 1"))
            with self.assertRaisesRegex(ValueError, "allocate a new replica"):
                lifecycle_evidence(directory, "omt")

    def test_bfcache_missing_fresh_attachment_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory)
            log = directory / "chrome.log"
            log.write_text(log.read_text().replace(log_line(12, 2300, 'render thread journal attached to "url-a"'), ""))
            with self.assertRaisesRegex(ValueError, "fresh journal"):
                lifecycle_evidence(directory, "omt")

    def test_bfcache_missing_fresh_paint_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory)
            trace = directory / "page-threads/trace.json"
            value = json.loads(trace.read_text())
            value["traceEvents"] = [event for event in value["traceEvents"] if event.get("name") != "ReplicaPage::Paint"]
            trace.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "fresh new-thread Paint"):
                lifecycle_evidence(directory, "omt")

    def test_bfcache_restored_pixels_and_fresh_mutation(self):
        frames = {name: {"cyanHeight": height, "followerY": height, "sha256": str(height)} for name, height in (("owner-a", 64), ("owner-b", 24), ("restored-a", 64), ("restored-mutated-a", 96))}
        self.assertEqual(lifecycle_pixel_verdict(frames), frames)
        frames["restored-mutated-a"] = dict(frames["restored-a"])
        with self.assertRaisesRegex(ValueError, "stale/incorrect"):
            lifecycle_pixel_verdict(frames)

    def test_bfcache_cached_surface_cannot_pass_fresh_paint(self):
        frames = {name: {"cyanHeight": height, "followerY": height, "sha256": str(height)} for name, height in (("owner-a", 64), ("owner-b", 24), ("restored-a", 64), ("restored-mutated-a", 96))}
        frames["restored-mutated-a"]["sha256"] = frames["owner-a"]["sha256"]
        with self.assertRaisesRegex(ValueError, "old cached surface"):
            lifecycle_pixel_verdict(frames)

    def test_lifecycle_one_shared_thread_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = write_lifecycle(directory)
            result["stages"][1]["renderThreads"].pop()
            (directory / "page-threads/threads.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "counts"):
                lifecycle_evidence(directory, "omt")

    def test_lifecycle_missing_stop_log_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_lifecycle(directory)
            log = directory / "chrome.log"
            log.write_text(log.read_text().replace("render thread stopped", "not a stop"))
            with self.assertRaisesRegex(ValueError, "stopped log"):
                lifecycle_evidence(directory, "omt")

    def test_lifecycle_old_thread_reused_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = write_lifecycle(directory)
            result["stages"][3]["renderThreads"] = copy.deepcopy(result["stages"][0]["renderThreads"])
            (directory / "page-threads/threads.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "retire"):
                lifecycle_evidence(directory, "omt")



START, END = {"pid": 11, "tid": 12, "ts": 1000000}, {"pid": 11, "tid": 12, "ts": 4000000}


def instant(name, tid, ts, **args):
    return {"name": name, "cat": "blink", "ph": "I", "pid": 11, "tid": tid, "ts": ts, "args": args}


def handoff_fixture():
    events = trace_fixture()
    events += [
        instant("ReplicaPage::TakeOver", 13, 1050000, main_task_ms=50),
        instant("RenderThreadJournal::BeginHandBack", 12, 4010000),
        {"name": "RenderThread::RunQuery", "ph": "X", "pid": 11, "tid": 12, "ts": 4020000, "dur": 500, "args": {"type": 28}},
        {"name": "ReplicaPage::AnswerQuery", "ph": "X", "pid": 11, "tid": 13, "ts": 4020100, "dur": 100, "args": {"type": 28}},
        instant("RenderThreadJournal::AnimationTimingsAdopted", 12, 4021000, adjusted=2, finished=0),
        {"name": "LocalFrameView::RunPaintLifecyclePhase", "ph": "X", "pid": 11, "tid": 12, "ts": 4030000, "dur": 300},
        {"name": "ReplicaPage::Paint", "ph": "X", "pid": 11, "tid": 13, "ts": 4035000, "dur": 300},
        instant("RenderThreadJournal::HandBack", 12, 4040000),
        {"name": "ReplicaPage::StopPresenting", "ph": "X", "pid": 11, "tid": 13, "ts": 4041000, "dur": 50},
        {"name": "LocalFrameView::RunPaintLifecyclePhase", "ph": "X", "pid": 11, "tid": 12, "ts": 4100000, "dur": 300},
    ]
    return events


def without(events, name, index=0):
    matches = [position for position, event in enumerate(events) if event.get("name") == name]
    return events[:matches[index]] + events[matches[index] + 1:]


def write_trace(folder, events):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trace.json").write_text(json.dumps({"traceEvents": events}))
    (folder / "trace-complete.json").write_text(json.dumps({"dataLossOccurred": False}))


def mark(name, ts, pid=11, tid=12):
    return {"name": f"validation:{name}", "cat": "blink.user_timing", "ph": "R", "pid": pid, "tid": tid, "ts": ts}


class HybridTests(unittest.TestCase):
    def test_animation_timings_enum(self):
        self.assertEqual(QUERY_TYPES["AnimationTimings"], 28)
        self.assertEqual(len(QUERY_TYPES), 29)

    def test_valid_takeover_and_hand_back(self):
        result = handoff_evidence(handoff_fixture(), "omt", START, END)
        self.assertEqual((result["renderTid"], result["takeoverLatencyMs"], result["handBackAfterEndMs"]), (13, 50, 40))
        self.assertEqual(result["mainPaintsAfterHandBack"], 1)
        self.assertEqual(result["animationTimingsAdopted"], {"adjusted": 2, "finished": 0})

    def test_takeover_late_missing_or_duplicated_fails(self):
        late = handoff_fixture()
        next(event for event in late if event["name"] == "ReplicaPage::TakeOver")["ts"] = 1300000
        cases = [(late, "limit 250ms"), (without(handoff_fixture(), "ReplicaPage::TakeOver"), "exactly one"), (handoff_fixture() + [instant("ReplicaPage::TakeOver", 13, 2000000)], "found 2")]
        for events, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                handoff_evidence(events, "omt", START, END)

    def test_takeover_on_main_or_other_process_fails(self):
        for change in ({"tid": 12}, {"pid": 99}):
            events = handoff_fixture()
            next(event for event in events if event["name"] == "ReplicaPage::TakeOver").update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "exactly one"):
                handoff_evidence(events, "omt", START, END)

    def test_hand_back_gates(self):
        slow = handoff_fixture()
        next(event for event in slow if event["name"] == "RenderThreadJournal::HandBack")["ts"] = 5100000
        wrong_type = handoff_fixture()
        for event in wrong_type:
            if event["name"] in ("RenderThread::RunQuery", "ReplicaPage::AnswerQuery"):
                event["args"]["type"] = 3
        cases = [
            (without(handoff_fixture(), "RenderThreadJournal::HandBack"), "one HandBack"),
            (without(handoff_fixture(), "RenderThreadJournal::BeginHandBack"), "one HandBack"),
            (slow, "limit 1000ms"),
            (without(handoff_fixture(), "RenderThreadJournal::AnimationTimingsAdopted"), "AnimationTimingsAdopted"),
            (without(handoff_fixture(), "RenderThread::RunQuery"), "Missing synchronous|Unpaired"),
            (wrong_type, "AnimationTimings"),
            (without(handoff_fixture(), "ReplicaPage::StopPresenting"), "StopPresenting"),
            (handoff_fixture() + [{"name": "ReplicaPage::Paint", "ph": "X", "pid": 11, "tid": 13, "ts": 4500000, "dur": 10}], "after StopPresenting"),
            (without(handoff_fixture(), "LocalFrameView::RunPaintLifecyclePhase", 1), "did not resume"),
        ]
        for events, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                handoff_evidence(events, "omt", START, END)

    def test_baseline_must_have_no_handoff_events(self):
        self.assertEqual(handoff_evidence(trace_fixture(False), "baseline", START, END), {"handoffEvents": 0})
        with self.assertRaisesRegex(ValueError, "hand-off"):
            handoff_evidence(trace_fixture(False) + [instant("ReplicaPage::TakeOver", 13, 1050000)], "baseline", START, END)

    def test_queries_before_takeover_are_not_counted(self):
        events = roundtrip_fixture() + [{"name": "RenderThread::RunQuery", "ph": "X", "ts": 1010000, "dur": 50, "pid": 11, "tid": 12, "args": {"type": 3}}]
        with self.assertRaisesRegex(ValueError, "enclose"):
            roundtrip_check(events)
        result = query_roundtrips(events, START, END, "omt", after=1050000)
        self.assertEqual(result["requests"], 1)
        self.assertEqual(query_roundtrips(trace_fixture(), START, END, "omt", minimum=0)["requests"], 0)

    def test_smoke_idle_mutations_follow_without_replica_paint(self):
        base = [mark("smoke-insert", 1000)] + [{"name": "LocalFrameView::RunPaintLifecyclePhase", "ph": "X", "pid": 11, "tid": 12, "ts": 1000 + ts, "dur": 5} for ts in range(6)]
        names = [{"ph": "M", "pid": 11, "tid": tid, "name": "thread_name", "args": {"name": name}} for tid, name in ((12, "CrRendererMain"), (13, "BlinkRenderThread"))]
        follow = {"name": "ReplicaPage::Follow", "ph": "X", "pid": 11, "tid": 13, "ts": 1100, "dur": 5}
        cases = [
            ("omt", base + names + [follow], None),
            ("omt", base + names, "did not follow"),
            ("omt", base + names + [follow, {**follow, "name": "ReplicaPage::Paint"}], "takeover/paint"),
            ("omt", base[:3] + names + [follow], "main-thread paints"),
            ("baseline", base + names, None),
            ("baseline", base + names + [follow], "baseline emitted replica"),
        ]
        for mode, events, message in cases:
            with self.subTest(mode=mode, message=message), tempfile.TemporaryDirectory() as temporary:
                write_trace(Path(temporary) / "smoke-trace", events)
                if message:
                    with self.assertRaisesRegex(ValueError, message):
                        smoke_trace_evidence(Path(temporary), mode)
                else:
                    smoke_trace_evidence(Path(temporary), mode)

    def test_unreplicable_requires_detach_and_stock_render(self):
        good_frame = {"cyanHeight": 264, "followerY": 264, "sha256": "x"}
        log = log_line(12, 100, "the render thread cannot reproduce this page")
        cases = [
            (log, [instant("RenderThreadJournal::Unreplicable", 12, 10)], good_frame, None),
            ("", [instant("RenderThreadJournal::Unreplicable", 12, 10)], good_frame, "log line"),
            (log, [], good_frame, "trace instant"),
            (log, [instant("RenderThreadJournal::Unreplicable", 12, 10), instant("ReplicaPage::TakeOver", 13, 20)], good_frame, "TakeOver"),
            (log, [instant("RenderThreadJournal::Unreplicable", 12, 10)], {**good_frame, "cyanHeight": 24}, "264px"),
        ]
        for text, events, frame, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary, patch("extended_analysis.frame_geometry", return_value=({}, frame)):
                directory = Path(temporary)
                write_trace(directory / "unreplicable", events)
                (directory / "chrome.log").write_text(text)
                (directory / "unreplicable" / "unreplicable.json").write_text(json.dumps({"completed": True, "startedMs": EPOCH, "logStart": 0, "logEnd": len(text), "after": {"panelHeight": 264}}))
                if message:
                    with self.assertRaisesRegex(ValueError, message):
                        validate_unreplicable(directory)
                else:
                    self.assertEqual(validate_unreplicable(directory)["unreplicableInstants"], 1)

    def memory_fixture(self, directory, mode="omt", growth=0.0, idle=100.0, extra_events=(), threads=None):
        events = [mark("churn-start", 1000000), mark("churn-end", 21000000)] + list(extra_events)
        events += [{"ph": "M", "pid": 11, "tid": 13, "name": "thread_name", "args": {"name": "BlinkRenderThread"}}]
        write_trace(directory / "mem", events)
        samples = []
        for index in range(23):
            t = index * 2000
            pss = 100 + growth * t / 1000 if t <= 20000 else idle
            samples.append({"epochMs": EPOCH + t, "renderers": [{"pid": 11, "pssKb": pss * 1024, "renderThreads": (1 if mode == "omt" else 0) if threads is None else threads}, {"pid": 99, "pssKb": 1, "renderThreads": 0}]})
        (directory / "mem" / "memory.json").write_text(json.dumps({"completed": True, "churnStart": {"epochMs": EPOCH}, "churnEnd": {"epochMs": EPOCH + 20000, "ticks": 1200}, "samples": samples}))
        return memory_evidence(directory, mode)

    def test_memory_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.memory_fixture(Path(temporary))
            self.assertEqual((result["pid"], result["idleMedianMb"], result["takeoversDuringChurn"]), (11, 100, 0))
            self.assertEqual(len(result["series"]), 23)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "grows"):
            self.memory_fixture(Path(temporary), growth=10)
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "TakeOver during"):
            self.memory_fixture(Path(temporary), extra_events=[instant("ReplicaPage::TakeOver", 13, 5000000)])
        for mode, threads in (("omt", 0), ("baseline", 1)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(ValueError, "presence"):
                self.memory_fixture(Path(temporary), mode=mode, threads=threads)
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.memory_fixture(Path(temporary), mode="baseline", growth=10)["lastChurnMedianMb"], 280)
        baseline = {"idleMedianMb": 100.0}
        self.assertEqual(compare_memory(baseline, {"idleMedianMb": 148.0})["deltaMb"], 48)
        with self.assertRaisesRegex(ValueError, "idle PSS"):
            compare_memory(baseline, {"idleMedianMb": 148.5})


if __name__ == "__main__":
    unittest.main()
