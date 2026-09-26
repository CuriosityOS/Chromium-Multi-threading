# Release validation context

The parent reports that a separately launched `blink_unittests` run using 28 jobs overlapped this validation run's start through **2026-09-26 18:39:33 UTC**, covering the baseline height/3s, grid/3s and queries/3s capture windows. All OMT cases begin after that overlap.

No validation gates, deadlines, assertions or pixel/trace thresholds are changed. Any baseline timing failure remains a failure and will be reported for a separately approved clean rerun. This overlap must be considered when interpreting timings; the run is not an unloaded baseline-versus-OMT performance benchmark.

Source of the overlap information: parent agent message during the run. Recorded timestamps confirm the baseline3s blocks at18:39:03.556–06.556,18:39:17.923–20.923 and18:39:26.571–29.571 UTC. Baseline10s measured blocks begin18:39:35.255; OMT measurements begin18:41:19.303, after the reported overlap.

Final result: **PASS, exit0**. Every baseline case, including all timing/capture gates, passed without relaxation. No clean rerun is triggered by a baseline failure. All four803-file manifests match SHA256 `9a63ea1594e8960360c463a939871a34d57635977a3be772f1b2c56edc4c3877`. Raw case timestamps remain in run.json and individual artifacts.
