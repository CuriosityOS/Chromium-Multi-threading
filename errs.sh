#!/bin/sh
ssh core 'python3 - <<"PY"
import re
s=open("/root/cr153/src/out/Omt/siso_output").read()
s=re.sub(r"\x1b\[[0-9;]*m", "", s)
seen=0
for m in re.finditer(r"^(\S+:\d+:\d+: error: .*)$", s, re.M):
    print(m.group(1)); seen+=1
    if seen>60: break
for m in re.finditer(r"^FAILED: .*$", s, re.M): print(m.group(0)[:200])
PY'
