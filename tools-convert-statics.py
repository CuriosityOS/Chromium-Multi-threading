#!/usr/bin/env python3
# Runs on core. Converts DEFINE_STATIC_LOCAL(Persistent<...>) sites in Blink
# core/platform to DEFINE_PER_THREAD_STATIC_LOCAL so that each thread gets its
# own garbage-collected singleton.
import re, subprocess, sys, os
root = '/root/cr153/src/third_party/blink/renderer'
os.chdir(root)
files = subprocess.run(['rg', '-l', '-U', r'DEFINE_(THREAD_SAFE_)?STATIC_LOCAL\(\s*(const\s+)?(Weak)?Persistent<',
                        'core', 'platform', '--glob', '!*test*'], capture_output=True, text=True).stdout.split()
pat = re.compile(r'DEFINE_(?:THREAD_SAFE_)?STATIC_LOCAL\((\s*(?:const\s+)?(?:Weak)?Persistent<)')
inc = '#include "third_party/blink/renderer/platform/wtf/per_thread_static.h"\n'
total = 0
for f in files:
    s = open(f).read()
    s2, n = pat.subn(r'DEFINE_PER_THREAD_STATIC_LOCAL(\1', s)
    if not n:
        continue
    if inc not in s2:
        lines = s2.splitlines(keepends=True)
        idx = [i for i, l in enumerate(lines) if l.startswith('#include "')]
        lines.insert(idx[-1] + 1, inc)
        s2 = ''.join(lines)
    open(f, 'w').write(s2)
    total += n
    print(f, n)
print('total', total)
