"""Render reviewed YAML diffs and bind confirmation to exact source content."""

import difflib
import hashlib
import json


def _unified_diff(before: str, after: str, rel_path: str, max_lines: int = 200) -> str:
    """Unified diff of a prospective write, capped for response size."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{rel_path} (before)",
            tofile=f"{rel_path} (after)",
        )
    )
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... diff truncated ({omitted} more lines)\n"]
    return "".join(lines)


def _confirm_token(normalized: str, raw_content: str, new_content: str) -> str:
    """Bind confirmation to the target, reviewed source, and proposed result."""
    # Replacing/removing a key can hide source edits in the proposed result.
    payload = json.dumps([normalized, raw_content, new_content])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
