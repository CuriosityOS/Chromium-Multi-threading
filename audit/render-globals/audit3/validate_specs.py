#!/usr/bin/env python3
"""Format/lint LOCAL proposed mirrors; remote operations are read-only."""
from collections import Counter, defaultdict
from pathlib import Path
import difflib
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[2]
PREFIX = 'third_party/blink/renderer/'
groups = json.loads((ROOT / 'spec-manifest.json').read_text())
requests = []
for group, edits in groups.items():
    byfile = defaultdict(list)
    for edit in edits:
        byfile[edit['path']].append(edit)
    for file, file_edits in byfile.items():
        original = (ROOT / 'snapshots' / file.removeprefix(PREFIX)).read_text()
        text = original
        for e in sorted(file_edits, key=lambda e: original.index(e['oldText']), reverse=True):
            text = text.replace(e['oldText'], e['newText'], 1)
        ranges = [[j1 + 1, max(j1 + 1, j2)] for tag, i1, i2, j1, j2 in
                  difflib.SequenceMatcher(None, original.splitlines(), text.splitlines()).get_opcodes()
                  if tag != 'equal']
        requests.append(dict(group=group, path=file, text=text, ranges=ranges))

remote_program = '''import sys,json,subprocess
reqs=json.load(sys.stdin)
for req in reqs:
 args=['/root/depot_tools/clang-format','--style=file','--sort-includes=false','--assume-filename=/root/cr153/src/'+req['path']]
 for start,end in req['ranges']: args.append(f'--lines={start}:{end}')
 p=subprocess.run(args,input=req['text'],text=True,capture_output=True,cwd='/root/cr153/src')
 if p.returncode: raise RuntimeError(p.stderr)
 req['formatted']=p.stdout
json.dump(reqs,sys.stdout)
'''
import shlex
result = subprocess.run(['ssh', 'core', 'python3 -c ' + shlex.quote(remote_program)],
                        input=json.dumps(requests), text=True, capture_output=True, check=True)
requests = json.loads(result.stdout)
final_groups = defaultdict(list)
for req in requests:
    original = (ROOT / 'snapshots' / req['path'].removeprefix(PREFIX)).read_text()
    before, after = original.splitlines(keepends=True), req['formatted'].splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, before, after)
    context = 1
    while True:
        op_groups = list(matcher.get_grouped_opcodes(context))
        if all(original.count(''.join(before[ops[0][1]:ops[-1][2]])) == 1
               for ops in op_groups):
            break
        context += 1
        assert context <= 12, req['path']
    for ops in op_groups:
        i1, i2, j1, j2 = ops[0][1], ops[-1][2], ops[0][3], ops[-1][4]
        old, new = ''.join(before[i1:i2]), ''.join(after[j1:j2])
        assert original.count(old) == 1, (req['path'], old)
        final_groups[req['group']].append(dict(path=req['path'], oldText=old.rstrip('\n'), newText=new.rstrip('\n'), line=i1+1))

# Check all new preimages together against freshly read remote sources, never
# attempting an application. Also save local proposed mirrors for lint.
byfile = defaultdict(list)
for edits in final_groups.values():
    for e in edits:
        byfile[e['path']].append(e)
remote_read = '''import sys,json,pathlib,hashlib
paths=json.load(sys.stdin)
print(json.dumps({p:pathlib.Path('/root/cr153/src',p).read_text() for p in paths}))
'''
fresh = subprocess.run(['ssh', 'core', 'python3 -c ' + shlex.quote(remote_read)],
                       input=json.dumps(list(byfile)), text=True, capture_output=True, check=True)
fresh = json.loads(fresh.stdout)
manifest = []
for file, edits in byfile.items():
    text = fresh[file]
    spans = []
    for e in edits:
        assert text.count(e['oldText']) == 1, (file, 'stale or ambiguous preimage', e['oldText'])
        i = text.index(e['oldText'])
        spans.append((i, i + len(e['oldText'])))
    spans.sort()
    assert all(a[1] <= b[0] for a,b in zip(spans,spans[1:])), (file, 'overlap')
    proposed = text
    for e in sorted(edits, key=lambda e: text.index(e['oldText']), reverse=True):
        proposed = proposed.replace(e['oldText'], e['newText'], 1)
    for directory, contents in [('fresh',text),('proposed',proposed)]:
        dst = ROOT / directory / file
        dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(contents)
    manifest.append(file + ' ' + hashlib.sha256(text.encode()).hexdigest())
(ROOT / 'fresh-sha256.txt').write_text('\n'.join(manifest)+'\n')
for group, edits in final_groups.items():
    (BASE / 'edits' / f'21-audit3-{group}.txt').write_text(''.join(
        f"@@@ {e['path']}\n<<<<\n{e['oldText']}\n====\n{e['newText']}\n>>>>\n" for e in edits))
(ROOT / 'formatted-manifest.json').write_text(json.dumps(final_groups, indent=2)+'\n')

# Recheck formatting on the combined proposals, since two specs can touch the
# same source file. The formatter reads stdin and prints; it writes no file.
checks=[]
for file in byfile:
    old=(ROOT/'fresh'/file).read_text(); new=(ROOT/'proposed'/file).read_text()
    ranges=[[j1+1,max(j1+1,j2)] for tag,i1,i2,j1,j2 in
            difflib.SequenceMatcher(None,old.splitlines(),new.splitlines()).get_opcodes() if tag!='equal']
    checks.append(dict(path=file,text=new,ranges=ranges))
check_program=remote_program.replace("p=subprocess.run(args,", "args += ['--dry-run','--Werror']\n p=subprocess.run(args,")
check=subprocess.run(['ssh','core','python3 -c '+shlex.quote(check_program)],input=json.dumps(checks),text=True,capture_output=True)
(ROOT/'format-validation.txt').write_text(f'exit={check.returncode}\n'+check.stderr)
if check.returncode:
    raise RuntimeError(check.stderr)

linter = BASE / 'audit/qualified-name/context/cpplint.py'
counts={}
for directory in ['fresh','proposed']:
    files=[str(ROOT/directory/file) for file in byfile]
    lint=subprocess.run([sys.executable,str(linter),'--project_root='+str(ROOT/directory),*files],text=True,capture_output=True)
    (ROOT/f'lint-{directory}.txt').write_text(lint.stdout+lint.stderr)
    normalized = lint.stderr.replace(str(ROOT/directory), '<MIRROR>')
    counts[directory]=Counter(re.sub(r':\d+', ':<LINE>', re.sub(r'^.*?:\d+:\s*','',line))
                              for line in normalized.splitlines()
                              if re.search(r'\[[^]]+/[^]]+\] \[\d\]$',line))
new_warnings=counts['proposed']-counts['fresh']
summary=f'{len(final_groups)} specs; {len(byfile)} files; {sum(map(len,final_groups.values()))} unique, non-overlapping current-remote preimages.\nChanged-line formatting: PASS.\nLint warnings: baseline {sum(counts["fresh"].values())}; proposed {sum(counts["proposed"].values())}; new {sum(new_warnings.values())}.\n'
summary+='\n'.join(f'{n}x {s}' for s,n in new_warnings.items())+'\nNo remote edits, builds, tests or git operations.\n'
(ROOT/'validation.txt').write_text(summary)
print(summary)
