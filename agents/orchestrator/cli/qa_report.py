#!/usr/bin/env python3
"""
QA Phase 2: Generate structured QA report, post as grava comment, save to docs/qa/reports/.

Expects a results JSON file written by Claude during Phase 1 review:
  {
    "items": [
      {"section": "Functional", "text": "...", "verdict": "PASS|FAIL|WARN|SKIP", "evidence": "..."},
      ...
    ]
  }

Usage: python3 qa_report.py <id> --results-file <path>
                             [--target-repo <path>] [--actor <name>]
Output: JSON {id, verdict, report_path, fail_count, blocking}
Exit codes:
  0 = ok
  1 = results file missing or malformed
  2 = write or comment failed

Algorithm:
  1. Load and validate results JSON (must have "items" list with required fields)
     exit 1 if missing or malformed
  2. Compute summary:
       total, pass_count, fail_count, warn_count, skip_count
       blocking_items = items where verdict == "FAIL"
  3. Overall verdict:
       any FAIL  → "fail"
       only WARN → "warn"
       else      → "pass"
  4. Render Markdown report with sections:
       # QA Report — <id>
       Overall: PASS/FAIL/WARN | summary counts
       ## Blocking Issues (if any FAILs)
       ## Checklist Results (all items, grouped by section)
  5. mkdir -p <target-repo>/docs/qa/reports/
     Atomic write to grava-<id>-qa-report.md (tmp → rename)
     exit 2 on write error
  6. grava comment <id> -m "<report, capped at 4096 chars + path note>"
     (no --file flag on grava comment — read content then pass via -m)
  7. Write wisps:
       qa_verdict, qa_report_path, qa_fail_count
       qa_blocking_items = JSON string of first 10 FAIL items
  8. Labels:
       verdict == "pass" → grava label <id> --add qa-passed
       else              → grava label <id> --add qa-failed
  9. grava commit -m "qa-agent: <id> QA report (<verdict>)"
  10. Print JSON {id, verdict, report_path, fail_count, blocking: [items]}
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERDICT_ICONS = {
    "PASS": "✅",
    "FAIL": "❌",
    "WARN": "⚠️",
    "SKIP": "⏭️",
}
COMMENT_MAX = 4096


def wisp_write(issue_id: str, key: str, value: str, cwd: str) -> None:
    subprocess.run(
        ["grava", "wisp", "write", issue_id, key, value],
        capture_output=True, cwd=cwd,
    )


def render_report(
    issue_id: str,
    issue_title: str,
    checklist_path: str,
    items: list[dict],
    verdict: str,
    fail_count: int,
    warn_count: int,
    pass_count: int,
    skip_count: int,
    blocking: list[str],
) -> str:
    total = len(items)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️"}.get(verdict, "❓")
    verdict_label = verdict.upper()

    lines = [
        f"# QA Report — {issue_id}",
        "",
        f"**Issue:** {issue_title}",
        f"**Reviewed by:** qa-agent",
        f"**Date:** {date_str}",
        f"**Checklist:** {checklist_path}",
        f"**Verdict:** {icon} {verdict_label} "
        f"({pass_count}/{total} pass, {fail_count} fail, {warn_count} warn, {skip_count} skip)",
        "",
        "## Results",
        "",
    ]

    # Group by section
    sections: dict[str, list[dict]] = {}
    for item in items:
        sec = item.get("section", "General")
        sections.setdefault(sec, []).append(item)

    for sec, sec_items in sections.items():
        sec_pass = sum(1 for i in sec_items if i.get("verdict") == "PASS")
        sec_total = sum(1 for i in sec_items if i.get("verdict") != "SKIP")
        lines.append(f"### {sec} ({sec_pass}/{sec_total})")
        for item in sec_items:
            icon_v = VERDICT_ICONS.get(item.get("verdict", ""), "❓")
            evidence = item.get("evidence", "").strip()
            lines.append(f"- {icon_v} {item.get('text', '')}")
            if evidence:
                lines.append(f"  *{evidence}*")
        lines.append("")

    if blocking:
        lines.append("## Blocking Issues")
        for idx, b in enumerate(blocking, 1):
            lines.append(f"{idx}. {b}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", help="Grava issue ID")
    parser.add_argument("--results-file", required=True)
    parser.add_argument("--target-repo", default=".")
    parser.add_argument("--actor", default="qa-agent")
    args = parser.parse_args(argv)

    cwd = args.target_repo

    # 1. Load results
    try:
        results = json.loads(Path(args.results_file).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot load results file '{args.results_file}': {exc}", file=sys.stderr)
        sys.exit(1)

    items = results.get("items")
    if not isinstance(items, list):
        print("ERROR: results file must have an 'items' list", file=sys.stderr)
        sys.exit(1)

    # 2. Compute stats
    fail_count = sum(1 for i in items if i.get("verdict") == "FAIL")
    warn_count = sum(1 for i in items if i.get("verdict") == "WARN")
    pass_count = sum(1 for i in items if i.get("verdict") == "PASS")
    skip_count = sum(1 for i in items if i.get("verdict") == "SKIP")
    blocking = [i["text"] for i in items if i.get("verdict") == "FAIL"][:10]

    verdict = "fail" if fail_count > 0 else "warn" if warn_count > 0 else "pass"

    # 3. Get issue title and checklist path from grava
    show_r = subprocess.run(
        ["grava", "show", args.id, "--json"],
        capture_output=True, text=True, cwd=cwd,
    )
    issue_title = args.id
    if show_r.returncode == 0:
        try:
            issue_title = json.loads(show_r.stdout).get("title", args.id)
        except Exception:
            pass

    checklist_r = subprocess.run(
        ["grava", "wisp", "read", args.id, "qa_checklist"],
        capture_output=True, text=True, cwd=cwd,
    )
    checklist_path = checklist_r.stdout.strip() if checklist_r.returncode == 0 else "unknown"

    # 4. Render report
    report = render_report(
        args.id, issue_title, checklist_path, items,
        verdict, fail_count, warn_count, pass_count, skip_count, blocking,
    )

    # 5. Save report
    reports_dir = os.path.join(cwd, "docs", "qa", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_filename = f"grava-{args.id}-qa-report.md"
    report_path = os.path.join(reports_dir, report_filename)
    rel_path = os.path.join("docs", "qa", "reports", report_filename)

    try:
        tmp = report_path + ".tmp"
        Path(tmp).write_text(report)
        os.replace(tmp, report_path)
    except OSError as exc:
        print(f"ERROR: cannot write report: {exc}", file=sys.stderr)
        sys.exit(2)

    # 6. Post grava comment (capped; grava comment has no --file flag)
    comment = report
    if len(comment) > COMMENT_MAX:
        comment = report[:COMMENT_MAX - 80] + f"\n\n...(truncated — full report at {rel_path})"
    subprocess.run(
        ["grava", "comment", args.id, "-m", comment],
        capture_output=True, cwd=cwd,
    )

    # 7. Write wisps
    wisp_write(args.id, "qa_verdict", verdict, cwd)
    wisp_write(args.id, "qa_report_path", rel_path, cwd)
    wisp_write(args.id, "qa_fail_count", str(fail_count), cwd)
    wisp_write(args.id, "qa_blocking_items", json.dumps(blocking), cwd)

    # 8. Labels
    label = "qa-passed" if verdict == "pass" else "qa-failed"
    subprocess.run(
        ["grava", "label", args.id, "--add", label],
        capture_output=True, cwd=cwd,
    )

    # 9. Commit
    subprocess.run(
        ["grava", "commit", "-m", f"qa-agent: {args.id} QA report ({verdict})"],
        capture_output=True, cwd=cwd,
    )

    print(json.dumps({
        "id": args.id,
        "verdict": verdict,
        "report_path": rel_path,
        "fail_count": fail_count,
        "blocking": blocking,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
