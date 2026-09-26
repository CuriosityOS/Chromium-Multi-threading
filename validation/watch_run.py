#!/usr/bin/env python3
"""Watch retained logs locally on Linux; emit only fatal stacks and completion."""
import json
from pathlib import Path
import sys
import time


def watch(directory, timeout=900):
    deadline = time.monotonic() + timeout
    seen = set()
    while time.monotonic() < deadline:
        for log in directory.glob("*/chrome.log"):
            lines = log.read_text(errors="replace").splitlines()
            for index, line in enumerate(lines):
                if "FATAL:" not in line and "Received signal" not in line:
                    continue
                key = (str(log), index)
                if key in seen:
                    continue
                frames = []
                for candidate in lines[index + 1:index + 80]:
                    if candidate.startswith("#"):
                        frames.append(candidate)
                    elif frames:
                        break
                    if len(frames) == 15:
                        break
                # Fatal stacks are written immediately; collect them on the next
                # filesystem read if this one raced the log writer.
                if len(frames) < 15 and not (directory / "exit-code").exists():
                    continue
                seen.add(key)
                print(json.dumps({"event": "FATAL", "log": str(log),
                                  "line": index + 1, "message": line,
                                  "frames": frames}), flush=True)
        completion = directory / "exit-code"
        if completion.exists():
            code = int(completion.read_text().strip())
            print(json.dumps({"event": "FINISHED" if code == 0 else "FAILED",
                              "exitCode": code, "directory": str(directory)}), flush=True)
            return code
        # This is local filesystem monitoring inside one SSH connection, not
        # polling a remote API or reconnecting SSH.
        time.sleep(1)
    print(json.dumps({"event": "FAILED", "reason": "completion timeout",
                      "directory": str(directory)}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(watch(Path(sys.argv[1])))
