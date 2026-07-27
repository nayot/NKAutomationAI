import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from edoc.config import DEFAULT_COMMAND

VALID_QUEUE_STATUSES = ("PROVISIONAL", "READY")
VALID_ACTIONS = ("signing", "skip")


class DocFileError(Exception):
    pass


@dataclass
class DocEntry:
    rank: int
    data_id: str
    title: str
    action: str
    command: str
    reason: str = ""
    summary: str = ""
    opinion: str = ""


@dataclass
class Queue:
    queue_status: str
    inbox: str
    generated: str
    docs: list[DocEntry] = field(default_factory=list)


_FIELD_RE = re.compile(r"^\s*-\s*\*\*([^:*]+):\*\*\s*(.*?)\s*$")
_HEADER_FIELD_RE = re.compile(r"^\*\*([^:*]+):\*\*\s*(.*?)\s*$")
_SECTION_RE = re.compile(r"^##\s+\d+\.\s*(.*?)\s*$")


def _strip_backticks(value: str) -> str:
    v = value.strip()
    if v.startswith("`") and v.endswith("`") and len(v) >= 2:
        v = v[1:-1]
    return v.strip()


def write_queue(ranked: list[dict], path: str, inbox_name: str) -> None:
    """Render the editable markdown queue. `ranked` items must have rank, data_id, title,
    summary, reason, command."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    lines.append("# eDoc Signing Queue")
    lines.append("")
    lines.append("**Queue Status:** `PROVISIONAL`")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Inbox:** {inbox_name}")
    lines.append(f"**Total:** {len(ranked)} documents")
    lines.append("")
    lines.append("> Review each document below. To skip one, change its **Action** from `signing` to `skip`.")
    lines.append("> When ready, change **Queue Status** above from `PROVISIONAL` to `READY` and save.")
    lines.append("> Then run `edoc --sign`.")
    lines.append(f"> Default command: {DEFAULT_COMMAND}")
    lines.append("")

    for item in ranked:
        title = item.get("title", "(no title)")
        lines.append("---")
        lines.append("")
        lines.append(f"## {item['rank']}. {title}")
        lines.append("")
        if item.get("summary"):
            lines.append(f"- **Summary:** {item['summary']}")
        if item.get("opinion"):
            lines.append(f"- **Opinions:** {item['opinion']}")
        lines.append(f"- **Data ID:** `{item['data_id']}`")
        lines.append("- **Action:** `signing`")
        lines.append(f"- **Command:** {item.get('command', DEFAULT_COMMAND)}")
        if item.get("attachment_path"):
            p = Path(item["attachment_path"]).resolve()
            lines.append(f"- **Attachment:** [{p.name}]({p})")
        if item.get("reason"):
            lines.append(f"- **AI reasoning:** {item['reason']}")
        lines.append("")

    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _parse_header(header_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in header_text.splitlines():
        m = _HEADER_FIELD_RE.match(line)
        if m:
            fields[m.group(1).strip().lower()] = _strip_backticks(m.group(2))
    return fields


def _parse_doc_block(block: str, block_index: int) -> DocEntry:
    title = ""
    fields: dict[str, str] = {}
    rank = 0

    for line in block.splitlines():
        sec_m = _SECTION_RE.match(line)
        if sec_m:
            heading = line.lstrip("#").strip()
            num_match = re.match(r"^(\d+)\.\s*(.*)$", heading)
            if num_match:
                rank = int(num_match.group(1))
                title = num_match.group(2).strip()
            continue
        f_m = _FIELD_RE.match(line)
        if f_m:
            fields[f_m.group(1).strip().lower()] = _strip_backticks(f_m.group(2))

    data_id = fields.get("data id") or fields.get("data_id")
    if not data_id:
        raise DocFileError(f"Block #{block_index}: missing 'Data ID' field")

    action_raw = fields.get("action", "")
    action = action_raw.lower()
    if action not in VALID_ACTIONS:
        raise DocFileError(
            f"Block #{block_index} (Data ID {data_id}): "
            f"Action must be 'signing' or 'skip', got {action_raw!r}"
        )

    command = fields.get("command") or DEFAULT_COMMAND

    return DocEntry(
        rank=rank,
        data_id=data_id,
        title=title,
        action=action,
        command=command,
        reason=fields.get("ai reasoning", ""),
        summary=fields.get("summary", ""),
        opinion=fields.get("opinions", ""),
    )


def read_queue(path: str) -> Queue:
    p = Path(path)
    if not p.exists():
        raise DocFileError(f"File not found: {path}")
    text = p.read_text(encoding="utf-8")

    blocks = re.split(r"\n---\s*\n", text)
    if len(blocks) < 2:
        raise DocFileError(f"{path}: no document blocks found (expected '---' separators).")

    header_fields = _parse_header(blocks[0])
    queue_status_raw = header_fields.get("queue status", "")
    queue_status = queue_status_raw.upper()
    if queue_status not in VALID_QUEUE_STATUSES:
        raise DocFileError(
            f"Queue Status must be 'PROVISIONAL' or 'READY', got {queue_status_raw!r}. "
            f"Edit the line `**Queue Status:** \\`READY\\`` at the top of {path}."
        )

    docs: list[DocEntry] = []
    seen_ids: set[str] = set()
    for i, block in enumerate(blocks[1:], 1):
        if not block.strip():
            continue
        entry = _parse_doc_block(block, i)
        if entry.data_id in seen_ids:
            raise DocFileError(f"Duplicate Data ID {entry.data_id} in {path}")
        seen_ids.add(entry.data_id)
        docs.append(entry)

    return Queue(
        queue_status=queue_status,
        inbox=header_fields.get("inbox", ""),
        generated=header_fields.get("generated", ""),
        docs=docs,
    )


def queue_has_ready_gate(path: str) -> bool:
    """Quick check: is documents.md gated READY? Used by fetch to refuse overwrite."""
    try:
        q = read_queue(path)
    except DocFileError:
        return False
    return q.queue_status == "READY"
