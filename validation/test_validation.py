import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from analyze import (
    CYAN,
    YELLOW,
    analyze_run,
    durations,
    locate_strip,
    pixel_verdict,
    ppm_image,
    stripe_geometry,
    trace_evidence,
)


def sample_frames(changing):
    return [
        {
            "epochMs": t,
            "cyanHeight": 24 + ((t - 1000) // 15 if changing else 0),
            "followerY": 24 + ((t - 1000) // 15 if changing else 0),
            "sha256": str(t if changing else 24),
        }
        for t in range(1000, 4001, 33)
    ]


def trace_fixture(omt=True):
    events = [
        {"ph": "M", "pid": 11, "tid": 12, "name": "thread_name", "args": {"name": "CrRendererMain"}},
        {"ph": "M", "pid": 11, "tid": 13, "name": "thread_name", "args": {"name": "BlinkRenderThread"}},
        {"ph": "X", "pid": 11, "tid": 12, "name": "RunTask", "ts": 900000, "dur": 3200000},
    ]
    for name, ts in [("mutation", 999999), ("block-start", 1000000), ("block-end", 4000000)]:
        events.append({"ph": "R", "cat": "blink.user_timing", "pid": 11, "tid": 12, "name": f"validation:{name}", "ts": ts})
    if omt:
        for ts in range(1300000, 3700000, 100000):
            for name in ("BeginFrame", "Paint"):
                events.append({"ph": "X", "cat": "blink", "pid": 11, "tid": 13, "name": f"ReplicaPage::{name}", "ts": ts, "dur": 300})
    return events


def check_trace(events, mode="omt"):
    return trace_evidence(events, mode, "^BlinkRenderThread$", "^ReplicaPage::(BeginFrame|Paint)$", 3000)


class EvidenceTests(unittest.TestCase):
    def test_baseline_static_is_valid_negative_control(self):
        self.assertEqual(pixel_verdict(sample_frames(False), 1000, 4000, "baseline")["heightChangeSteps"], 0)

    def test_omt_must_change_layout(self):
        self.assertGreater(pixel_verdict(sample_frames(True), 1000, 4000, "omt")["heightRangePx"], 30)
        with self.assertRaisesRegex(ValueError, "fewer"):
            pixel_verdict(sample_frames(False), 1000, 4000, "omt")

    def test_baseline_changing_fails(self):
        with self.assertRaisesRegex(ValueError, "Baseline"):
            pixel_verdict(sample_frames(True), 1000, 4000, "baseline")

    def test_changes_outside_block_do_not_count(self):
        frames = sample_frames(False)
        frames[0]["cyanHeight"] = 5
        frames[-1]["cyanHeight"] = 264
        with self.assertRaisesRegex(ValueError, "fewer"):
            pixel_verdict(frames, 1000, 4000, "omt")

    def test_single_jump_not_animation(self):
        frames = sample_frames(False)
        for frame in frames:
            if frame["epochMs"] > 2000:
                frame.update(cyanHeight=264, followerY=264, sha256="jump")
        with self.assertRaisesRegex(ValueError, "fewer"):
            pixel_verdict(frames, 1000, 4000, "omt")

    def test_no_sibling_false_positive(self):
        frames = sample_frames(True)
        frames[20]["followerY"] = 0
        with self.assertRaisesRegex(ValueError, "not following"):
            pixel_verdict(frames, 1000, 4000, "omt")

    def test_gapped_capture_fails(self):
        frames = [frame for frame in sample_frames(True) if not 2000 < frame["epochMs"] < 3000]
        with self.assertRaisesRegex(ValueError, "gap"):
            pixel_verdict(frames, 1000, 4000, "omt")

    def test_capture_must_cover_block(self):
        with self.assertRaisesRegex(ValueError, "late block"):
            pixel_verdict(sample_frames(True)[:70], 1000, 4000, "omt")

    def test_external_strip_and_ppm(self):
        width, height = 400, 320
        data = bytearray(width * height * 3)
        for y in range(10, 34):
            data[(y * width + 20) * 3:(y * width + 370) * 3] = CYAN * 350
        roi = locate_strip(width, height, bytes(data))
        self.assertEqual(roi, {"x": 322, "y": 10, "width": 32, "height": 290})
        ppm = b"P6\n400 320\n255\n" + data
        self.assertEqual(ppm_image(ppm), (width, height, data))
        with self.assertRaisesRegex(ValueError, "missing"):
            locate_strip(width, height, bytes(width * height * 3))
        frame = CYAN * (32 * 24) + YELLOW * (32 * 24) + bytes(32 * (290 - 48) * 3)
        self.assertEqual(stripe_geometry(frame), (24, 24))

    def test_valid_trace_and_baseline(self):
        result = check_trace(trace_fixture())
        self.assertEqual(result["main"]["tid"], 12)
        self.assertEqual(result["renderThreads"][0]["tid"], 13)
        check_trace(trace_fixture(False), "baseline")

    def test_compositor_is_not_render_thread(self):
        events = trace_fixture()
        events[1]["args"]["name"] = "Compositor"
        with self.assertRaisesRegex(ValueError, "No sustained"):
            check_trace(events)

    def test_begin_frame_without_paint_fails(self):
        events = [event for event in trace_fixture() if event["name"] != "ReplicaPage::Paint"]
        with self.assertRaisesRegex(ValueError, "No sustained"):
            check_trace(events)

    def test_main_thread_render_does_not_pass(self):
        events = trace_fixture()
        for event in events:
            if event["name"].startswith("ReplicaPage"):
                event["tid"] = 12
        with self.assertRaisesRegex(ValueError, "No sustained"):
            check_trace(events)

    def test_other_process_does_not_pass(self):
        events = trace_fixture()
        for event in events:
            if event.get("tid") == 13:
                event["pid"] = 99
        with self.assertRaisesRegex(ValueError, "No sustained"):
            check_trace(events)

    def test_missing_milestone_fails(self):
        with self.assertRaisesRegex(ValueError, "milestone"):
            check_trace([event for event in trace_fixture() if event["name"] != "validation:block-end"])

    def test_task_must_enclose_mutation_and_block(self):
        events = trace_fixture()
        events[2]["ts"] = 1000000
        with self.assertRaisesRegex(ValueError, "encloses mutation"):
            check_trace(events)

    def test_short_loop_fails(self):
        events = trace_fixture()
        events[5]["ts"] = 3000000
        with self.assertRaisesRegex(ValueError, "too short"):
            check_trace(events)

    def test_baseline_with_omt_events_fails(self):
        with self.assertRaisesRegex(ValueError, "unexpectedly"):
            check_trace(trace_fixture(), "baseline")

    def test_be_pairing_never_crosses_threads(self):
        events = [
            {"ph": "B", "pid": 1, "tid": 1, "ts": 0, "name": "a"},
            {"ph": "E", "pid": 1, "tid": 2, "ts": 2},
            {"ph": "E", "pid": 1, "tid": 1, "ts": 3},
        ]
        self.assertEqual(list(durations(events))[0]["dur"], 3)

    def test_missing_run_cases_fail_and_keep_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "run.json").write_text(json.dumps({"cases": [], "failures": ["Synthetic crash"]}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(analyze_run(output))
            self.assertTrue((output / "analysis.json").exists())
            self.assertIn("FAIL", (output / "REPORT.md").read_text())

    def test_browser_launch_requires_explicit_gate(self):
        result = subprocess.run(["node", str(Path(__file__).parent / "run.mjs")], capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED", result.stderr)
        self.assertIn("No Chromium was launched", result.stderr)

    def test_trace_fixture_not_mutated(self):
        events = trace_fixture()
        previous = copy.deepcopy(events)
        check_trace(events)
        self.assertEqual(previous, events)


if __name__ == "__main__":
    unittest.main()
