"""Static product UI contract checks used by the v4.1.0 release gate."""

from __future__ import annotations

import html.parser
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable


SOURCE_TEMPLATES = {
    "agents.html", "approvals.html", "audit.html", "branches.html", "collab.html",
    "graph.html", "knowledge.html", "login.html", "loops.html", "memory.html",
    "monitor.html", "portal_chat.html", "portal_login.html", "skills.html",
    "specs.html", "tasks.html", "workspaces.html",
}
ENTERPRISE_TEMPLATES = {"approvals.html", "audit.html"}
LEGACY_MARKERS = (
    "#1a1a2e", "#16213e", "#0f3460", "#0d1b2a", "#1a1a3e",
    "#e0e0e0", "#a0a0b0", "#4fc3f7", "#e94560", "Segoe UI",
    "var(--bg-primary)", "var(--bg-secondary)", "var(--bg-card)",
    "var(--text-primary)", "var(--text-secondary)", "var(--accent)",
)
EMOJI_ENTITIES = ("&#9998;", "&#10005;", "&#10004;", "&#10006;", "&#128269;", "&#128206;")
LOCAL_SCRIPT_NAMES = {"chuanxu.js", "chuanxu-prepaint.js"}


class _MarkupParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.ids: list[str] = []
        self.tags: list[tuple[str, dict[str, str], str]] = []
        self.buttons: list[tuple[dict[str, str], str]] = []
        self._button_stack: list[tuple[dict[str, str], list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = {key: value or "" for key, value in attrs}
        if "id" in normalized:
            self.ids.append(normalized["id"])
        self.tags.append((tag, normalized, "start"))
        if tag == "button":
            self._button_stack.append((normalized, []))
        elif self._button_stack:
            self._button_stack[-1][1].append("")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button_stack:
            attrs, text = self._button_stack.pop()
            self.buttons.append((attrs, "".join(text).strip()))
        self.tags.append((tag, {}, "end"))

    def handle_data(self, data: str) -> None:
        if self._button_stack:
            self._button_stack[-1][1].append(data)

    def handle_entityref(self, name: str) -> None:
        if self._button_stack:
            self._button_stack[-1][1].append("&" + name + ";")

    def handle_charref(self, name: str) -> None:
        if self._button_stack:
            self._button_stack[-1][1].append("&#" + name + ";")


def _template_dir(root: Path) -> Path:
    candidate = root / "scripts" / "visualization" / "templates"
    return candidate if candidate.is_dir() else root / "shared" / "visualization" / "templates"


def _static_dir(root: Path) -> Path:
    candidate = root / "scripts" / "visualization" / "static"
    return candidate if candidate.is_dir() else root / "shared" / "visualization" / "static"


def _resolve_local_asset(static_dir: Path, value: str) -> bool:
    path = value.split("#", 1)[0]
    if not path:
        return True
    if path.startswith("/static/"):
        return (static_dir / path.removeprefix("/static/")).is_file()
    return not path.startswith(("http://", "https://", "//"))


def _check_javascript(source: str, filename: str) -> list[str]:
    source = re.sub(r"\{\{[^{}]+\}\}", "300", source)
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        path = Path(handle.name)
        handle.write(source)
    try:
        result = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        path.unlink(missing_ok=True)
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "syntax error"
        return [f"{filename}: JavaScript syntax: {detail[:180]}"]
    return []


def validate_template(path: Path, static_dir: Path, generated: bool = False) -> list[str]:
    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    name = path.name
    style_tags = re.findall(r"<style\b[^>]*>", text, flags=re.IGNORECASE)
    if any("cx-prepaint" not in tag for tag in style_tags):
        issues.append(f"{name}: inline <style> remains")
    if any(marker in text for marker in LEGACY_MARKERS):
        found = [marker for marker in LEGACY_MARKERS if marker in text]
        issues.append(f"{name}: legacy foundation markers {found}")
    if any(entity in text for entity in EMOJI_ENTITIES):
        issues.append(f"{name}: emoji/entity action icon remains")
    if not re.search(r'href="/static/pages/[^"]+\.css"', text):
        issues.append(f"{name}: page stylesheet is not local")
    for required in ('href="/static/chuanxu.css"', 'src="/static/chuanxu.js"', 'src="/static/chuanxu-prepaint.js"'):
        if required not in text:
            issues.append(f"{name}: missing {required}")
    if generated and "{{" in text:
        issues.append(f"{name}: unresolved placeholder")

    parser = _MarkupParser()
    try:
        parser.feed(text)
    except Exception as exc:
        issues.append(f"{name}: HTML parse: {type(exc).__name__}")
    duplicate_ids = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    if duplicate_ids:
        issues.append(f"{name}: duplicate IDs {duplicate_ids[:8]}")
    for attrs, label in parser.buttons:
        if not label and not attrs.get("aria-label") and not attrs.get("title"):
            issues.append(f"{name}: unnamed button")
    for tag, attrs, _ in parser.tags:
        if tag not in {"link", "script", "img", "use"}:
            continue
        value = attrs.get("href" if tag in {"link", "use"} else "src", "")
        if value and not _resolve_local_asset(static_dir, value):
            issues.append(f"{name}: non-local {tag} asset {value}")
    scripts = re.findall(
        r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for index, script in enumerate(scripts, 1):
        if script.strip():
            issues.extend(_check_javascript(script, f"{name}#script{index}"))
    return issues


def validate_product_tree(root: Path, enterprise: bool, generated: bool = False) -> list[str]:
    """Validate source or one generated package and return human-readable issues."""
    template_dir = _template_dir(root)
    static_dir = _static_dir(root)
    if not template_dir.is_dir() or not static_dir.is_dir():
        return [f"{root}: product template/static directory missing"]
    expected = set(SOURCE_TEMPLATES)
    if not enterprise:
        expected -= ENTERPRISE_TEMPLATES
    actual = {path.name for path in template_dir.glob("*.html")}
    issues = [f"templates: missing {sorted(expected - actual)}"] if expected - actual else []
    unexpected = actual - expected
    if unexpected:
        issues.append(f"templates: unexpected {sorted(unexpected)}")
    for name in sorted(actual & expected):
        issues.extend(validate_template(template_dir / name, static_dir, generated=generated))
    for name in LOCAL_SCRIPT_NAMES:
        path = static_dir / name
        if not path.is_file():
            issues.append(f"static: missing {name}")
        else:
            issues.extend(_check_javascript(path.read_text(encoding="utf-8"), name))
    for path in sorted((static_dir / "pages").glob("*.css")):
        text = path.read_text(encoding="utf-8")
        found = [marker for marker in LEGACY_MARKERS if marker in text]
        if found:
            issues.append(f"{path.name}: legacy foundation markers {found}")
    return issues


def validate_source(root: Path) -> list[str]:
    return validate_product_tree(root, enterprise=True, generated=False)


def validate_all_packages(build_output: Path, edition_names: Iterable[tuple[str, bool]]) -> list[str]:
    issues: list[str] = []
    for name, enterprise in edition_names:
        issues.extend(
            f"{name}: {issue}"
            for issue in validate_product_tree(build_output / name, enterprise, generated=True)
        )
    return issues
