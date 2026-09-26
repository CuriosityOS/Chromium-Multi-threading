#!/usr/bin/env python3
"""Static-only Python/HTML/test-invariant checks. No browser launch."""
import ast
from html.parser import HTMLParser
from pathlib import Path

root = Path(__file__).resolve().parent
for path in root.glob("*.py"):
    ast.parse(path.read_text(), filename=str(path))


class DemoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            assert values["id"] not in self.ids, f"Duplicate HTML id: {values['id']}"
            self.ids.add(values["id"])
        if tag not in {"meta", "link", "br", "hr", "input", "img"}:
            self.stack.append(tag)
        if tag in {"script", "link"}:
            assert (root / "demo" / values.get("src", values.get("href", ""))).is_file()

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, f"Unbalanced HTML element: {tag}"


for name, required in {
    "index.html": {"proof", "panel", "fill", "follower", "smoke", "heartbeat"},
    "queries.html": {"height-panel", "grid-panel", "shadow-host", "input-button", "query-container"},
}.items():
    parser = DemoParser()
    parser.feed((root / "demo" / name).read_text())
    assert not parser.stack, f"Unclosed HTML elements in {name}"
    assert required <= parser.ids, f"Missing test elements in {name}"
script = (root / "demo/demo.js").read_text()
assert "document.timeline" not in script, "Main timeline must not be used as render evidence"
critical = script.split('panel.classList.toggle("open");', 1)[1].split('milestone("block-end"', 1)[0]
for forbidden in ("requestAnimationFrame(", "setTimeout(", "await ", "getComputedStyle(", "getBoundingClientRect("):
    assert forbidden not in critical, f"Yield or forced layout in critical region: {forbidden}"
queries = (root / "demo/queries.js").read_text()
query_task = queries.split("function runQueryBlock", 1)[1].split("window.validation", 1)[0]
for forbidden in ("requestAnimationFrame(", "setTimeout(", "await "):
    assert forbidden not in query_task, f"Yield in query task: {forbidden}"
assert query_task.count('classList.toggle("open")') == 2, "Both transitions must start in one task"
for path in (root / "demo").glob("*.css"):
    css = path.read_text()
    assert css.count("{") == css.count("}"), f"Unbalanced CSS blocks: {path.name}"
    for forbidden in ("transform:", "opacity:", "animation:"):
        assert forbidden not in css, f"Compositor confound in demo: {forbidden}"
print("Python AST, HTML structure, assets and critical-region lint passed")
