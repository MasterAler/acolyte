"""Публикация: черновик страницы в Confluence (Server/DC) и выгрузка для knowledge-RAG."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import requests


def md_to_storage(md: str) -> str:
    md = re.sub(r"&(?!(amp|lt|gt);)", "&amp;", md)
    md = md.replace("<", "&lt;").replace(">", "&gt;")
    lines = md.splitlines()
    out, in_list = [], False
    for ln in lines:
        h = re.match(r"^(#{1,4})\s+(.*)", ln)
        li = re.match(r"^\s*[-*]\s+(.*)", ln)
        if h:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = min(len(h.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{h.group(2)}</h{lvl}>")
        elif li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{li.group(1)}</li>")
        elif not ln.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{ln}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _confluence_ready(cfg) -> bool:
    return bool(cfg.confluence_url and cfg.confluence_user and cfg.confluence_token and cfg.confluence_space)


def publish_confluence(session_dir: Path, cfg) -> str:
    summary = (Path(session_dir) / "summary.md").read_text(encoding="utf-8")
    m = re.match(r"#\s+(.+)", summary)
    title = f"[ЧЕРНОВИК] {(m.group(1).strip() if m else 'Встреча')} — {date.today():%Y-%m-%d}"
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": cfg.confluence_space},
        "body": {"storage": {"value": md_to_storage(summary), "representation": "storage"}},
    }
    if cfg.confluence_parent_id:
        payload["ancestors"] = [{"id": str(cfg.confluence_parent_id)}]
    r = requests.post(
        f"{cfg.confluence_url.rstrip('/')}/rest/api/content",
        auth=(cfg.confluence_user, cfg.confluence_token),
        json=payload,
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Confluence {r.status_code}: {r.text[:300]}")
    page = r.json()
    return f"{cfg.confluence_url.rstrip('/')}{page['_links']['webui']}"


def export_rag(session_dir: Path, cfg, chunk_chars: int = 1800) -> Path:
    """Готовый jsonl для knowledge-индекса; само индексирование делается инструментами memory-rag."""
    session_dir = Path(session_dir)
    summary = (session_dir / "summary.md").read_text(encoding="utf-8")
    m = re.match(r"#\s+(.+)", summary)
    title = (m.group(1).strip() if m else "Встреча") + f" ({session_dir.name})"
    paras, buf = [], []
    for ln in summary.splitlines():
        buf.append(ln)
        if sum(len(x) for x in buf) >= chunk_chars:
            paras.append("\n".join(buf).strip())
            buf = []
    if (t := "\n".join(buf).strip()):
        paras.append(t)
    cfg.rag_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.rag_jsonl, "a", encoding="utf-8") as f:
        for i, p in enumerate(paras, 1):
            f.write(json.dumps({
                "text": p,
                "metadata": {
                    "source_path": str(session_dir / "summary.md"),
                    "title": title,
                    "chunk": i,
                    "date": str(date.today()),
                },
            }, ensure_ascii=False) + "\n")
    return cfg.rag_jsonl
