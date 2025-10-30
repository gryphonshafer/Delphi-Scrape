#!/usr/bin/env python3
"""
Generate a static, browsable snapshot of a Delphi Forums scrape.

Reads thread, profile, and binary data from the `store/` directory and emits an
HTML site with locally resolved images and attachments so the archive can be
viewed offline without connecting to the Delphi backend.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

import yaml

# Regex lifted from the original scraper to mirror file hashing behaviour.
HASH_EXT_RE = re.compile(r"(\.[^./?&=\-]{1,5})$")
STRIP_TAG_RE = re.compile(r"<[^>]+>")
INDEX_THREADS_PER_FOLDER = 6

STYLE_CSS = """\
:root {
    color-scheme: light;
    font-size: 16px;
}

* {
    box-sizing: border-box;
}

body {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    background: #F9F5DF;
    color: #1f2933;
    margin: 0;
    min-height: 100vh;
}

a {
    color: #0052cc;
    text-decoration: none;
}

a:hover,
a:focus {
    text-decoration: underline;
}

header {
    background: #1f3d63;
    color: #ffffff;
    padding: 2rem 1rem;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.3);
}

header h1 {
    margin: 0;
    font-size: 1.85rem;
}

header p {
    margin: 0.6rem 0 0;
    font-size: 1rem;
    opacity: 0.85;
}

main {
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem 1rem 3rem;
}

.folder-preview {
    background: #ffffff;
    border-radius: 14px;
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
    padding: 1.75rem;
    margin-bottom: 2.5rem;
}

.folder-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.25rem;
}

.folder-header h2 {
    margin: 0;
    font-size: 1.3rem;
    color: #9900A2;
}

.folder-subtitle {
    margin-top: 0.4rem;
    font-size: 0.9rem;
    color: #475569;
}

.folder-show-all {
    background: #009900;
    color: #ffffff;
    padding: 0.35rem 0.9rem;
    border-radius: 999px;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    white-space: nowrap;
}

.folder-show-all:hover,
.folder-show-all:focus {
    background: #007700;
    text-decoration: none;
}

.thread-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 1.1rem;
}

.thread-card {
    display: block;
    background: #fdf7e3;
    border-radius: 12px;
    padding: 1rem 1.15rem;
    box-shadow: inset 0 0 0 1px rgba(31, 61, 99, 0.08);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.thread-card:hover,
.thread-card:focus-within {
    transform: translateY(-3px);
    box-shadow: 0 10px 20px rgba(31, 61, 99, 0.2);
    text-decoration: none;
}

.thread-card h3 {
    margin: 0;
    font-size: 1.05rem;
    color: #143d6d;
}

.thread-card-meta {
    margin-top: 0.35rem;
    font-size: 0.85rem;
    color: #475569;
}

.thread-card-snippet {
    margin: 0.6rem 0 0.8rem;
    font-size: 0.92rem;
    color: #334155;
    line-height: 1.45;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.thread-card-stats {
    font-size: 0.8rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

footer {
    max-width: 1100px;
    margin: 0 auto 2.5rem;
    padding: 0 1rem;
    font-size: 0.85rem;
    color: #94a3b8;
}

.folder-page header {
    padding-bottom: 1.5rem;
}

.folder-page main {
    padding-top: 1.5rem;
}

.folder-page .folder-preview {
    background: #ffffff;
    padding: 1.75rem;
    border-radius: 14px;
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
}

.folder-table {
    width: 100%;
    border-collapse: collapse;
    background: #ffffff;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
}

.folder-table thead {
    background: #f0f4f8;
}

.folder-table th,
.folder-table td {
    padding: 0.75rem 1rem;
    text-align: left;
    border-bottom: 1px solid #e2e8f0;
    font-size: 0.92rem;
    color: #1f2933;
}

.folder-table th {
    font-weight: 600;
    color: #9900A2;
}

.folder-table tbody tr:nth-child(even) {
    background: #fdf7e3;
}

.folder-table tbody tr:hover {
    background: #f1f5ff;
}

.folder-table a {
    color: #143d6d;
    font-weight: 600;
}

.folder-table .thread-id {
    font-variant-numeric: tabular-nums;
    color: #475569;
}

.thread-wrapper {
    max-width: 900px;
    margin: 0 auto;
    padding: 2rem 1rem 4rem;
}

.thread-header {
    background: #ffffff;
    border-radius: 14px;
    padding: 1.75rem;
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
    margin-bottom: 1.75rem;
}

.thread-header h2 {
    margin: 0;
    font-size: 1.65rem;
    color: #0f172a;
}

.thread-header dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.5rem 1rem;
    margin: 1.2rem 0 0;
    font-size: 0.95rem;
}

.thread-header dt {
    font-weight: 600;
    color: #475569;
}

.thread-header dd {
    margin: 0;
    color: #1f2933;
}

.thread-nav {
    display: inline-flex;
    gap: 0.6rem;
    font-size: 0.9rem;
    margin-top: 1.2rem;
}

.message {
    background: #ffffff;
    border-radius: 14px;
    box-shadow: 0 4px 10px rgba(15, 23, 42, 0.12);
    margin-bottom: 1.5rem;
    overflow: hidden;
}

.message-header {
    background: #CCCCCC;
    color: #1f2933;
    padding: 0.65rem 1.25rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.9rem;
}

.msg-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
}

.msg-row-top .msg-date-time {
    margin-left: auto;
}

.msg-row-bottom .msg-seq {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
}

.msg-label {
    font-weight: 600;
}

.msg-author-name,
.msg-recipient-name {
    color: #000099;
    font-weight: 600;
}

.msg-recipient-extra {
    color: #000099;
    font-weight: 400;
}

.msg-date-time {
    font-variant-numeric: tabular-nums;
}

.message-body {
    padding: 1.25rem 1.25rem 1.5rem;
    font-size: 0.96rem;
    line-height: 1.6;
    color: #1e293b;
}

.msg-thread-ref {
    text-align: right;
    font-size: 0.85rem;
    color: #475569;
    margin-bottom: 0.75rem;
}

.msg-thread-ref a {
    color: #0f62fe;
}

.message-content p {
    margin: 0.6rem 0;
}

.message-content img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0.75rem auto;
}

.polltable {
    width: min(520px, 100%);
    margin: 1.5rem auto;
    border: 1px solid #d9d9d9;
    border-radius: 12px;
    background: #ffffff;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.05);
    overflow: hidden;
}

.polltable td {
    padding: 0.4rem 0.6rem;
}

.polltable .winbig {
    display: block;
    font-size: 1.05rem;
    font-weight: 600;
    color: #0f172a;
    text-align: center;
}

.polltable table {
    width: 100% !important;
}

.polltable tr:first-child td {
    border-bottom: 1px solid #e2e8f0;
}

.polltable td[class^="pollbar"] {
    padding: 0;
    height: 18px;
    border-bottom: 1px solid #000000;
    border-right: 1px solid #000000;
}

.polltable td.pollbar1 { background-color: #0000aa; }
.polltable td.pollbar2 { background-color: #d40000; }
.polltable td.pollbar3 { background-color: #2aaa00; }
.polltable td.pollbar4 { background-color: #f4aa00; }
.polltable td.pollbar5 { background-color: #d42ad4; }

.polltable .msgtxt {
    font-size: 0.85rem;
    color: #475569;
}

.polltable tr td:first-child {
    font-weight: 500;
    color: #1f2937;
}

.profile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    font-size: 0.82rem;
    color: #64748b;
    margin-top: 1.1rem;
}

.message-attachments {
    margin-top: 1.2rem;
    padding-top: 0.9rem;
    border-top: 1px solid #e2e8f0;
    font-size: 0.9rem;
}

.message-attachments h4 {
    margin: 0 0 0.4rem;
    font-size: 0.95rem;
    color: #334155;
}

.message-attachments ul {
    padding-left: 1.1rem;
    margin: 0;
}

.message-attachments li {
    margin: 0.35rem 0;
}

.msg-status {
    color: #9923AE;
    font-weight: 600;
}

.notice {
    background: #fff4ce;
    color: #614715;
    padding: 0.75rem 1rem;
    border-radius: 10px;
    margin: 1.5rem 0;
    font-size: 0.9rem;
}

.breadcrumb {
    margin-bottom: 1.2rem;
    font-size: 0.92rem;
    color: #475569;
}
"""


def slugify(value: str) -> str:
    if not value:
        return "forum"
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    slug = slug.strip("-")
    return slug or "forum"


def strip_html(text: Optional[str]) -> str:
    if text is None:
        return ""
    plain = STRIP_TAG_RE.sub(" ", text)
    plain = html.unescape(plain)
    plain = re.sub(r"\s+", " ", plain)
    return plain.strip()


def build_snippet(text: Optional[str], max_length: int = 180) -> str:
    plain = strip_html(text)
    if len(plain) <= max_length:
        return plain
    truncated = plain[: max_length].rsplit(" ", 1)[0].strip()
    if not truncated:
        truncated = plain[: max_length].strip()
    if truncated.endswith((".", ",", ";")):
        truncated = truncated.rstrip(".,;")
    return truncated + "..."


def pluralize(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"


def format_time_component(timestamp: dt.datetime) -> str:
    hour = timestamp.hour % 12 or 12
    suffix = "AM" if timestamp.hour < 12 else "PM"
    return f"{hour}:{timestamp.minute:02d}{suffix}"


def format_date_short(timestamp: Optional[dt.datetime]) -> Optional[str]:
    if not timestamp:
        return None
    return f"{timestamp.month}/{timestamp.day:02d}/{timestamp.year % 100:02d}"


def format_card_timestamp(timestamp: Optional[dt.datetime]) -> Optional[str]:
    if not timestamp:
        return None
    month = timestamp.strftime("%b")
    return f"{month} {timestamp.day:02d}, {timestamp.year} {format_time_component(timestamp)}"


def format_folder_date(timestamp: Optional[dt.datetime]) -> str:
    if not timestamp:
        return "Unknown"
    return f"{timestamp.month:02d}/{timestamp.day:02d}/{timestamp.year:04d}"


def format_name_html(
    name: Optional[str],
    primary_class: str,
    status: Optional[str] = None,
) -> str:
    raw = (name or "").strip()
    local_status = status
    if not raw:
        primary = "Unknown"
        extra = ""
    else:
        if not local_status and raw.lower().endswith(" unread"):
            raw = raw[: -len("unread")].rstrip()
            local_status = "unread"
        primary = raw
        extra = ""
        if raw.endswith(")") and "(" in raw:
            idx = raw.find("(")
            segment = raw[idx:].strip()
            if segment.count("(") == segment.count(")"):
                primary = raw[:idx].strip() or raw
                extra = segment
    if local_status and local_status.lower() == "unread":
        local_status = "unread"
    primary_html = f'<span class="{primary_class}">{html.escape(primary)}</span>'
    extra_html = (
        f' <span class="msg-recipient-extra">{html.escape(extra)}</span>' if extra else ""
    )
    status_html = (
        f' <span class="msg-status">{html.escape(local_status)}</span>'
        if local_status
        else ""
    )
    return primary_html + extra_html + status_html


def render_thread_card(thread: Mapping, *, href_prefix: str) -> str:
    title = html.escape(thread.get("title") or f"Thread {thread.get('id')}")
    link = f"{href_prefix}threads/{thread['id']}.html"

    author = thread.get("first_author")
    meta_html = (
        f'<div class="thread-card-meta">By {html.escape(author)}</div>' if author else ""
    )

    snippet = thread.get("snippet")
    snippet_html = (
        f'<p class="thread-card-snippet">{html.escape(snippet)}</p>' if snippet else ""
    )

    stats_parts = []
    count = thread.get("message_count", 0)
    stats_parts.append(f"{count} {pluralize('message', count)}")

    last_timestamp = format_card_timestamp(thread.get("last_date"))
    if last_timestamp:
        stats_parts.append(f"Last activity {last_timestamp}")

    views = thread.get("views")
    if views not in (None, "", 0, "0"):
        stats_parts.append(f"{views} views")

    stats_text = " | ".join(stats_parts)
    stats_html = (
        f'<div class="thread-card-stats">{html.escape(stats_text)}</div>'
        if stats_text
        else ""
    )

    return (
        "<li>"
        f'<a class="thread-card" href="{link}">'
        f"<h3>{title}</h3>"
        f"{meta_html}"
        f"{snippet_html}"
        f"{stats_html}"
        "</a>"
        "</li>"
    )




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Delphi Forums YAML threads into a standalone HTML archive."
    )
    parser.add_argument(
        "--store",
        default="store",
        help="Path to the scraper output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default="site_export",
        help="Destination directory for generated HTML (default: %(default)s)",
    )
    parser.add_argument(
        "--forum-title",
        default="Delphi Forum Archive",
        help="Title to display for the exported forum (default: %(default)s)",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> Mapping:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def hash_for_url(url: str) -> str:
    """Mirror the scraper's hashing logic so local files can be resolved."""
    file_part = url
    ext = ""
    match = HASH_EXT_RE.search(file_part)
    if match:
        ext = match.group(1)
        file_part = file_part[: match.start(1)]
    digest = hashlib.sha1(file_part.encode("utf-8")).hexdigest()
    return f"{digest}{ext}"


def ensure_local_asset(url: str, store_files: Path, export_files: Path) -> Optional[str]:
    """
    Copy the hashed binary for a remote URL into the export folder if present.
    Returns a relative path suitable for embedding in HTML. Falls back to None
    when the binary was not captured.
    """
    if not url:
        return None

    hashed_name = hash_for_url(url)
    source = store_files / hashed_name
    if not source.exists():
        return None

    destination = export_files / hashed_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
    return f"files/{hashed_name}"


def parse_date(raw: Optional[str]) -> Optional[dt.datetime]:
    if not raw:
        return None

    for fmt in ("%a %b %d %H:%M:%S %Y", "%a %b %e %H:%M:%S %Y"):
        try:
            return dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def render_index_html(
    forum_title: str, description: str, folders: List[Dict]
) -> str:
    sections: List[str] = []
    for folder in folders:
        threads = folder.get("threads") or []
        if not threads:
            continue

        preview_threads = threads[:INDEX_THREADS_PER_FOLDER]
        cards = "".join(
            render_thread_card(thread, href_prefix="") for thread in preview_threads
        )

        thread_total = len(threads)
        message_total = sum(t.get("message_count", 0) for t in threads)
        subtitle_parts = [f"{thread_total} {pluralize('thread', thread_total)}"]
        if message_total:
            subtitle_parts.append(f"{message_total} {pluralize('message', message_total)}")
        subtitle = " | ".join(subtitle_parts)

        section_html = (
            '<section class="folder-preview">'
            '<div class="folder-header">'
            "<div>"
            f"<h2>{html.escape(folder['name'])}</h2>"
            f'<p class="folder-subtitle">{html.escape(subtitle)}</p>'
            "</div>"
            f'<a class="folder-show-all" href="folders/{folder["slug"]}.html">Show All</a>'
            "</div>"
            f'<ul class="thread-list">{cards}</ul>'
            "</section>"
        )
        sections.append(section_html)

    sections_html = (
        "".join(sections)
        if sections
        else '<p class="notice">No forums were captured in this archive.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(forum_title)}</title>
  <link rel="stylesheet" href="assets/style.css"/>
</head>
<body>
  <header>
    <h1>{html.escape(forum_title)}</h1>
    <p>{html.escape(description)}</p>
  </header>
  <main>
    {sections_html}
  </main>
  <footer>
    Export generated on {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.
  </footer>
</body>
</html>
"""


def render_folder_html(
    forum_title: str,
    folder: Mapping,
) -> str:
    threads = folder.get("threads") or []
    thread_total = len(threads)
    message_total = sum(t.get("message_count", 0) for t in threads)

    subtitle_parts = []
    if thread_total:
        subtitle_parts.append(f"{thread_total} {pluralize('thread', thread_total)}")
    if message_total:
        subtitle_parts.append(f"{message_total} {pluralize('message', message_total)}")
    subtitle = " | ".join(subtitle_parts) or "No captured content."

    if threads:
        threads_sorted = sorted(
            threads,
            key=lambda t: (
                t.get("first_date") or dt.datetime.max,
                t.get("id"),
            ),
        )
        rows = []
        for thread in threads_sorted:
            thread_id = html.escape(str(thread.get("id")))
            title = html.escape(thread.get("title") or f"Thread {thread_id}")
            first_date = format_folder_date(thread.get("first_date"))
            author = html.escape(thread.get("first_author") or "Unknown")
            replies = max(thread.get("message_count", 0) - 1, 0)
            link = f'../threads/{thread["id"]}.html'
            rows.append(
                "<tr>"
                f'<td class="thread-id">{thread_id}</td>'
                f'<td><a href="{link}">{title}</a></td>'
                f"<td>{first_date}</td>"
                f"<td>{author}</td>"
                f"<td>{replies}</td>"
                "</tr>"
            )
        content_html = (
            '<table class="folder-table">'
            "<thead>"
            "<tr>"
            "<th>Thread ID</th>"
            "<th>Message Title</th>"
            "<th>Date Posted</th>"
            "<th>Author</th>"
            "<th>Replies</th>"
            "</tr>"
            "</thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    else:
        content_html = '<p class="notice">No threads were captured for this forum.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(folder.get('name') or 'Forum')} - {html.escape(forum_title)}</title>
  <link rel="stylesheet" href="../assets/style.css"/>
</head>
<body class="folder-page">
  <header>
    <h1>{html.escape(forum_title)}</h1>
    <p>Forum: {html.escape(folder.get('name') or 'Unknown')}</p>
  </header>
  <main>
    <section class="folder-preview">
      <div class="folder-header">
        <div>
          <h2>{html.escape(folder.get('name') or 'Forum')}</h2>
          <p class="folder-subtitle">{html.escape(subtitle)}</p>
        </div>
        <a class="folder-show-all" href="../index.html">Back to Index</a>
      </div>
      {content_html}
    </section>
  </main>
  <footer>
    Export generated on {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.
  </footer>
</body>
</html>
"""


def render_thread_html(
    forum_title: str,
    thread: Mapping,
    messages_html: str,
) -> str:
    folder = html.escape(thread.get("folder") or "Uncategorised")
    topic = html.escape(thread.get("title") or f"Thread {thread.get('id')}")
    views = html.escape(str(thread.get("views"))) if thread.get("views") else "N/A"
    message_count = thread.get("message_count", 0)
    first = thread.get("first_date")
    last = thread.get("last_date")
    first_display = first.strftime("%b %d, %Y %I:%M %p") if first else "N/A"
    last_display = last.strftime("%b %d, %Y %I:%M %p") if last else "N/A"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{topic} - {html.escape(forum_title)}</title>
  <link rel="stylesheet" href="../assets/style.css"/>
</head>
<body>
  <div class="thread-wrapper">
    <nav class="breadcrumb"><a href="../index.html">&larr; Back to forum index</a></nav>
    <section class="thread-header">
      <h2>{topic}</h2>
      <dl>
        <dt>Folder</dt><dd>{folder}</dd>
        <dt>Thread ID</dt><dd>{html.escape(str(thread.get("id")))}</dd>
        <dt>Messages</dt><dd>{message_count}</dd>
        <dt>Views</dt><dd>{views}</dd>
        <dt>First Posted</dt><dd>{html.escape(first_display)}</dd>
        <dt>Last Updated</dt><dd>{html.escape(last_display)}</dd>
      </dl>
    </section>
    {messages_html}
  </div>
</body>
</html>
"""


def build_profile_lookup(profiles_dir: Path) -> Dict[str, Mapping]:
    lookup: Dict[str, Mapping] = {}
    if not profiles_dir.exists():
        return lookup

    for path in profiles_dir.glob("*.yaml"):
        data = load_yaml(path)
        key = path.stem
        lookup[key] = data
    return lookup


def profile_key_from_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return name.replace("/", "_")


def describe_profile(profile: Optional[Mapping]) -> str:
    if not profile:
        return ""

    details = []
    for label in ("Member Since", "Last visit", "Location", "Interests"):
        value = profile.get(label)
        if value:
            details.append(f"{html.escape(label)}: {html.escape(str(value))}")
    if not details:
        return ""
    return '<div class="profile-meta">' + " | ".join(details) + "</div>"


def render_messages(
    messages: Iterable[Mapping],
    profile_lookup: Mapping[str, Mapping],
    store_files: Path,
    export_files: Path,
) -> str:
    messages = list(messages)
    total = len(messages)
    if not total:
        return '<p class="notice">No messages were captured for this thread.</p>'

    rendered: List[str] = []
    for index, msg in enumerate(messages, start=1):
        mid = msg.get("id") or "unknown"
        anchor = f"msg-{mid.replace('.', '-')}"
        raw_author = msg.get("from") or "Unknown"
        raw_recipient = msg.get("to") or "All"
        author_html = format_name_html(
            raw_author, "msg-author-name", msg.get("from_status")
        )
        recipient_html = format_name_html(
            raw_recipient, "msg-recipient-name", msg.get("to_status")
        )
        posted_raw = msg.get("date") or ""
        posted_dt = parse_date(posted_raw)
        date_display = format_date_short(posted_dt) if posted_dt else posted_raw
        time_display = format_time_component(posted_dt) if posted_dt else ""
        timestamp_text = date_display.strip()
        if time_display:
            timestamp_text = f"{timestamp_text} {time_display}"
        timestamp_html = html.escape(timestamp_text)

        content_html = msg.get("content") or ""
        attachments_html = ""
        attachment_items: List[str] = []

        for attachment in msg.get("attachments") or []:
            href = attachment.get("href")
            local = ensure_local_asset(href, store_files, export_files)
            link_target = local or href
            label = attachment.get("name") or href
            label_text = html.escape(label)
            size = attachment.get("size")
            size_text = f" ({html.escape(size)})" if size else ""
            if local:
                attachment_items.append(
                    f'<li><a href="../{link_target}" download>{label_text}</a>{size_text}</li>'
                )
            else:
                attachment_items.append(
                    f'<li><a href="{html.escape(link_target)}">{label_text}</a>{size_text} (remote)</li>'
                )

        if attachment_items:
            attachments_html = (
                '<div class="message-attachments">'
                "<h4>Attachments</h4>"
                f"<ul>{''.join(attachment_items)}</ul>"
                "</div>"
            )

        for image_url in msg.get("images") or []:
            local_image = ensure_local_asset(image_url, store_files, export_files)
            if local_image:
                content_html = content_html.replace(image_url, f"../{local_image}")

        pk = profile_key_from_name(msg.get("from"))
        profile_html = ""
        if pk:
            profile_html = describe_profile(profile_lookup.get(pk))

        seq_link = f'<a href="#{anchor}">{index} of {total}</a>'
        top_row_parts = [
            '<span class="msg-label msg-from">From: '
            f"{author_html}"
            "</span>"
        ]
        if timestamp_html:
            top_row_parts.append(
                f'<span class="msg-date-time">{timestamp_html}</span>'
            )

        bottom_row_parts = [
            '<span class="msg-label msg-to">To: '
            f"{recipient_html}"
            "</span>",
            f'<span class="msg-seq">({seq_link})</span>',
        ]

        header_html = (
            '<header class="message-header">'
            '<div class="msg-row msg-row-top">'
            + "".join(top_row_parts)
            + "</div>"
            '<div class="msg-row msg-row-bottom">'
            + "".join(bottom_row_parts)
            + "</div>"
            "</header>"
        )

        thread_ref_parts: List[str] = []
        if mid:
            thread_ref_parts.append(f"<strong>{html.escape(mid)}</strong>")
        reply_to = msg.get("in_reply_to")
        if reply_to:
            reply_anchor = f"msg-{reply_to.replace('.', '-')}"
            thread_ref_parts.append(
                f'in reply to <a href="#{reply_anchor}">{html.escape(reply_to)}</a>'
            )
        thread_ref_html = (
            f'<div class="msg-thread-ref">{" ".join(thread_ref_parts)}</div>'
            if thread_ref_parts
            else ""
        )

        body_sections: List[str] = []
        if thread_ref_html:
            body_sections.append(thread_ref_html)
        if content_html:
            body_sections.append(f'<div class="message-content">{content_html}</div>')
        else:
            body_sections.append('<div class="message-content"></div>')
        if profile_html:
            body_sections.append(profile_html)
        if attachments_html:
            body_sections.append(attachments_html)

        rendered.append(
            f'<article class="message" id="{anchor}">'
            f"{header_html}"
            f'<div class="message-body">{"".join(body_sections)}</div>'
            "</article>"
        )
    return "\n".join(rendered)


def main() -> None:
    args = parse_args()
    store_root = Path(args.store).resolve()
    export_root = Path(args.output).resolve()

    threads_dir = store_root / "threads"
    files_dir = store_root / "files"
    profiles_dir = store_root / "profiles"

    if not threads_dir.exists():
        raise SystemExit(f"No threads found at {threads_dir}")

    export_threads_dir = export_root / "threads"
    export_assets_dir = export_root / "assets"
    export_files_dir = export_root / "files"
    export_folders_dir = export_root / "folders"

    export_root.mkdir(parents=True, exist_ok=True)
    export_threads_dir.mkdir(parents=True, exist_ok=True)
    export_assets_dir.mkdir(parents=True, exist_ok=True)
    export_files_dir.mkdir(parents=True, exist_ok=True)
    export_folders_dir.mkdir(parents=True, exist_ok=True)

    # Write CSS asset.
    css_path = export_assets_dir / "style.css"
    css_path.write_text(STYLE_CSS, encoding="utf-8")

    profile_lookup = build_profile_lookup(profiles_dir)

    threads: List[Dict] = []
    for yaml_path in sorted(threads_dir.glob("*.yaml")):
        data = load_yaml(yaml_path)
        processed_messages = list(data.get("messages") or [])
        if not processed_messages:
            continue

        first_date = parse_date(processed_messages[0].get("date"))
        last_date = parse_date(processed_messages[-1].get("date"))

        metadata = data.get("metadata") or {}
        thread_id = str(data.get("thead_id") or yaml_path.stem)
        title = metadata.get("topic") or f"Thread {thread_id}"
        folder = metadata.get("folder") or "Uncategorised"
        views = metadata.get("views")
        folder_slug = slugify(folder)

        first_message = processed_messages[0]
        snippet = build_snippet(first_message.get("content"))
        first_author = first_message.get("from")
        message_count = len(processed_messages)

        rendered_messages = render_messages(
            processed_messages, profile_lookup, files_dir, export_files_dir
        )
        thread_html = render_thread_html(
            args.forum_title,
            {
                "id": thread_id,
                "title": title,
                "folder": folder,
                "views": views,
                "message_count": message_count,
                "first_date": first_date,
                "last_date": last_date,
            },
            rendered_messages,
        )

        thread_output_path = export_threads_dir / f"{thread_id}.html"
        thread_output_path.write_text(thread_html, encoding="utf-8")

        threads.append(
            {
                "id": thread_id,
                "title": title,
                "folder": folder,
                "folder_slug": folder_slug,
                "views": views,
                "message_count": message_count,
                "first_date": first_date,
                "last_date": last_date,
                "first_author": first_author,
                "snippet": snippet,
            }
        )

    # Assemble folder view for index.
    folders: Dict[str, Dict] = {}
    for thread in threads:
        folder_name = thread["folder"] or "Uncategorised"
        folder_slug = thread.get("folder_slug") or slugify(folder_name)
        bucket = folders.setdefault(
            folder_name,
            {"name": folder_name, "slug": folder_slug, "threads": []},
        )
        bucket.setdefault("slug", folder_slug)
        bucket["threads"].append(thread)

    for folder in folders.values():
        folder["threads"].sort(
            key=lambda t: (t["last_date"] or dt.datetime.min, t["id"]), reverse=True
        )

    folder_sections = sorted(folders.values(), key=lambda item: item["name"].lower())
    index_html = render_index_html(
        args.forum_title,
        "Offline snapshot generated from Delphi Forums scrape.",
        folder_sections,
    )

    for folder in folder_sections:
        folder_page_html = render_folder_html(args.forum_title, folder)
        (export_folders_dir / f"{folder['slug']}.html").write_text(
            folder_page_html, encoding="utf-8"
        )

    (export_root / "index.html").write_text(index_html, encoding="utf-8")


if __name__ == "__main__":
    main()
