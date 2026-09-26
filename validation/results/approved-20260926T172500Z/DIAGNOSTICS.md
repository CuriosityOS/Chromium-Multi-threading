# Approved BFCache build: overall FAIL, no fatal signatures

Run: `/root/cr153/validation/results/approved-20260926T172500Z`; exit1.
All12 recorded baseline/OMT cases passed. Full restored-page evidence and the paired native-input comparison remain incomplete; this run is not retroactively promoted to PASS.

## Recorded proof

- Every baseline:0 layout changes,0px range,1 ROI hash.
- OMT3s height/grid/queries:66 changes;218/218/219px guarded range; approximately2167ms motion.
- OMT10s height/grid/queries:233/233/234 changes;233/233/234px range;7733/7733/7766ms motion.
- Both query ROIs pass. Main PID/TID2491512; per-case render TIDs2491870,2492016,2492071,2492163,2492348,2492582.
- Both query durations pass68 exact assertions and exactly match baseline.155/365 same-type main/render query pairs; maximum waits1042/1439µs. Window scroll restores at6.973/5.549ms by trace, before the unchanged250ms guard.
- Zero MainThreadFallback in every block. Each OMT query block has10 separately counted informational SkippedForFocus entries. One pre-block fallback in height/10s remains reported, not failed.
- Both fatal-signature files are empty; no fatal event from the watcher.

## Native input

OMT's individual native-input checks pass: trusted mousedown/up/click, input-button, offsets20/15, correct focus.18 paired forwarding queries include HitTest19 and MouseRelativePosition21; max wait580µs. Main PID/TID2492856, render TID2492876. The explicit pointer readback successfully handles the stationary pointer.

Baseline input is incomplete because the earlier resize smoke failed before restoring the window. Geometry readiness preceded the resize console event; the code immediately asserted the event instead of waiting for it. The real resize event appeared approximately8ms after the smoke stage had already failed. The window remained1080×720; subsequent native target786/785 lay outside it, with xdotool reporting WINDOW927 (root) rather than2097155 (Chrome). Therefore the current-build paired native-input comparison is not proven.

The follow-up harness waits for both changed geometry and its matching fresh resize event, restores captured original bounds in finally, verifies restoration geometry, and retains resize.json even on failure. No resize/event assertion is removed.

## BFCache: actual hit, but harness aborted too early

Both modes really emitted fresh pageshow.persisted=true after history.back(). CDP also replayed the original cached console entry first. The readiness filter incorrectly selected that old pageshow(false) because it checked delivery-array position/URL but not occurrence time.

| Mode | Back request epochMs | Replayed initial event | Fresh persisted=true event |
|---|---:|---:|---:|
| baseline |1790443649652|1790443646629|1790443649659|
| OMT |1790443782751|1790443779704|1790443782759|

These entries are retained in each mode's page-cdp.jsonl; Chromium's own console log separately records the fresh true event. V8's upstream RuntimeAgent restore() calls enable(), which reports stored console messages, explaining the replay.

OMT's completed thread stages are1→2→1→1 in renderer2492856:

- A: replica3, TID2492943.
- A+peer: add replica4, TID2492961.
- Peer closed: original A thread survives.
- A→B: replica5, TID2492969 replaces A; BFCache-entry and thread-stop logs present.
- After history.back(), raw logs show replica6/TID2492999 created, answered a query and submitted its first frame. The harness aborted on the replayed false entry before the final process snapshot, explicit restored64px geometry/token assertions, or fresh96px mutation/captures.

Thus actual cache restoration and a new replica are observed, but full BFCache lifetime/fresh-pixel gates remain unexecuted, not passed. Only pre-navigation A64px/B24px captures exist. The fixed readiness filter requires the milestone's own epoch at/after the back request while retaining all replayed logs. It still returns a genuinely fresh persisted=false event for explicit cache-miss failure.

## Outside-block entries

These do not affect the strict zero-in-block gate:

- OMT input:5 fallbacks (layout28×3,13×1,17×1), plus6 informational focus skips.
- OMT page-lifetime:13 fallbacks (layout28×7,17×3,13×3), no focus skips.

Detailed sidecars: omt/input/outside-fallbacks-diagnostic.json and omt/page-threads/outside-fallbacks-diagnostic.json.

## Build identity, evidence and follow-up

All four791-file manifests match:
`d683cb43ff6c627da03f819fd38e29fcf7e76a548785598c3b12f571f9db70d9`.

- chrome: `d4b3ddeab1f58f3beb6a78ce017018dc6d77b378ae9b5678595eb3ed5ea4f910`
- libblink_core.so: `927577ff21ec4ee5c528f71262d4acd841a2beee4c574c9b701389d0e2cf1e0a`
- libblink_platform.so: `7e39cae87fe40c97058fc55be89296b9ad8d7a9c04d2330d1b6cdce658998f04`

The complete evidence (except browser profiles) is copied locally. The original run harness is archived. No own-profile processes remain. Post-run readiness fixes pass83 tests (61Python+22Node), formatting/lint/syntax/ShellCheck locally/remotely; no Chromium was launched during those checks. Any rerun needs explicit approval, and will use a new result directory. No Chromium source/build files were changed by validation.
