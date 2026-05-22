"""Format and submit reviewer bug reports via Vercel proxy → Linear (ADR-0019)."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import urllib.error
import urllib.request

from qc_core.plugin_config import FEEDBACK_PROXY_URL, PLUGIN_VERSION, SUBJECT_PREFIX

MAX_BODY_CHARS = 12_000
FINGERPRINT_RE = re.compile(r"^FINGERPRINT\s*\n(\S+)", re.MULTILINE)


def compute_fingerprint(skill: str, command: str, summary: str) -> str:
    payload = f"{skill}\n{command}\n{summary}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def truncate_body(body: str) -> str:
    if len(body) <= MAX_BODY_CHARS:
        return body
    omitted = len(body) - MAX_BODY_CHARS
    return body[:MAX_BODY_CHARS] + f"\n\n… truncated {omitted} characters"


def format_subject(title: str) -> str:
    title = title.strip()
    prefix = f"{SUBJECT_PREFIX} "
    if title.lower().startswith(SUBJECT_PREFIX.lower()):
        return title
    return f"{prefix}{title}"


def extract_fingerprint(body: str) -> str:
    match = FINGERPRINT_RE.search(body)
    return match.group(1) if match else ""


def build_body(
    *,
    skill: str,
    project: str,
    what_happened: str,
    command: str,
    expected: str = "",
    actual: str = "",
    repro_steps: str = "",
    fingerprint: str = "",
    extra: str = "",
) -> str:
    fp = fingerprint or compute_fingerprint(skill, command, what_happened)
    sections = [
        "Report from redicheck-ai plugin (/report-issue)",
        "",
        "ENVIRONMENT",
        f"- Plugin version: {PLUGIN_VERSION}",
        f"- Skill: {skill}",
        f"- OS: {platform.system()} {platform.release()}",
        f"- Python: {platform.python_version()}",
        "",
        "PROJECT",
        project,
        "",
        "WHAT HAPPENED",
        what_happened,
        "",
        "COMMAND",
        command.strip(),
    ]
    if expected:
        sections.extend(["", "EXPECTED", expected])
    if actual:
        sections.extend(["", "ACTUAL", actual])
    if repro_steps:
        sections.extend(["", "REPRO STEPS", repro_steps])
    if extra:
        sections.extend(["", "ADDITIONAL CONTEXT", extra])
    sections.extend(
        [
            "",
            "FINGERPRINT",
            fp,
            "",
            "Note: project names are included intentionally for debugging (ADR-0019).",
        ]
    )
    return truncate_body("\n".join(sections))


def format_dry_run(*, proxy_url: str, title: str, body: str) -> str:
    subject = format_subject(title)
    body = truncate_body(body.strip())
    fingerprint = extract_fingerprint(body)
    payload: dict[str, str] = {
        "title": subject,
        "description": body,
    }
    if fingerprint:
        payload["fingerprint"] = fingerprint
    lines = [
        "Dry run — would POST to feedback proxy (ADR-0019)",
        f"URL: {proxy_url}",
        "",
        "Payload:",
        json.dumps(payload, indent=2),
    ]
    return "\n".join(lines)


def submit_report(
    *,
    proxy_url: str,
    title: str,
    body: str,
    fingerprint: str = "",
    timeout: float = 30.0,
) -> dict[str, str]:
    subject = format_subject(title)
    body = truncate_body(body.strip())
    fp = fingerprint or extract_fingerprint(body)
    payload = {"title": subject, "description": body}
    if fp:
        payload["fingerprint"] = fp

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        proxy_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"redicheck-ai/{PLUGIN_VERSION}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Proxy HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Proxy request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Proxy returned invalid JSON: {raw[:500]}") from exc

    if not parsed.get("ok"):
        error = parsed.get("error", raw)
        raise RuntimeError(f"Proxy error: {error}")

    identifier = parsed.get("identifier", "")
    url = parsed.get("url", "")
    if not identifier or not url:
        raise RuntimeError(f"Proxy response missing issue fields: {raw[:500]}")

    return {"identifier": identifier, "url": url}


def format_success(*, identifier: str, url: str) -> str:
    return "\n".join(
        [
            "Submitted to Linear Feedback.",
            f"Issue: {identifier}",
            f"URL: {url}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Submit a bug report to Linear via the feedback proxy (ADR-0019)."
    )
    parser.add_argument("--title", required=True, help="Short summary (issue title tail)")
    parser.add_argument("--body", help="Plain-text body (or use --body-file)")
    parser.add_argument(
        "--body-file",
        type=argparse.FileType("r", encoding="utf-8"),
        help="Read body from file (use - for stdin)",
    )
    parser.add_argument(
        "--proxy-url",
        default=FEEDBACK_PROXY_URL,
        help=f"Feedback proxy URL (default: {FEEDBACK_PROXY_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload without submitting",
    )
    args = parser.parse_args(argv)

    if args.body_file:
        body = args.body_file.read()
    elif args.body:
        body = args.body
    else:
        parser.error("Provide --body or --body-file")

    if args.dry_run:
        print(format_dry_run(proxy_url=args.proxy_url, title=args.title, body=body))
        return 0

    try:
        result = submit_report(
            proxy_url=args.proxy_url,
            title=args.title,
            body=body,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_success(identifier=result["identifier"], url=result["url"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
