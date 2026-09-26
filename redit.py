#!/usr/bin/env python3
"""Apply exact-replacement edits to files on core.
Spec format:
@@@ path/relative/to/src
<<<<
old text
====
new text
>>>>
(repeat <<<< ==== >>>> blocks; multiple @@@ sections allowed)
"""
import json, subprocess, sys
text = open(sys.argv[1]).read()
specs = []
for sec in text.split("@@@ ")[1:]:
    path, rest = sec.split("\n", 1)
    edits = []
    for blk in rest.split("<<<<\n")[1:]:
        old, rest2 = blk.split("\n====\n", 1)
        new = rest2.split("\n>>>>", 1)[0]
        edits.append({"old": old, "new": new})
    specs.append({"file": path.strip(), "edits": edits})
r = subprocess.run(["ssh", "core", "/root/cr153/tools/edit.py"], input=json.dumps(specs), text=True)
sys.exit(r.returncode)
