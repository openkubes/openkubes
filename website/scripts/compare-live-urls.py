#!/usr/bin/env python3
"""Compare live public URLs with a deployed Cloudflare candidate.

Run manually from a network-enabled environment. Never modifies hosting.
An old URL that is reachable on production (2xx or 3xx) must not return a
404/5xx on the candidate. Redirect targets are reported for manual review.
"""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REPORT = Path(".mkdocs-site/url-compatibility-report.json")
def probe(base, path, timeout):
    url = base.rstrip("/") + path
    request = Request(url, headers={"User-Agent": "OpenKubes-OK196-URL-Audit/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return {"status": response.status, "final_url": response.url}
    except HTTPError as error:
        return {"status": error.code, "final_url": error.url}
    except (URLError, TimeoutError, OSError) as error:
        return {"status": None, "error": str(error)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", default="https://openkubes.org")
    parser.add_argument("--candidate", required=True, help="The candidate deployment hostname, not production")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=Path("url-http-comparison.json"))
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if args.live.rstrip("/") == args.candidate.rstrip("/"):
        parser.error("Live and candidate must be different hostnames")
    report = json.loads(args.manifest.read_text(encoding="utf-8"))
    urls = set(report["required_paths"])
    urls.update(x["possible_legacy_html_url"] for x in report["markdown_html_candidates_to_verify"])
    urls.update(x["source"] for x in report["markdown_html_candidates_to_verify"])
    rows = []
    regressions = []
    unresolved = []
    for path in sorted(urls):
        before = probe(args.live, path, args.timeout)
        after = probe(args.candidate, path, args.timeout)
        old = before.get("status")
        new = after.get("status")
        regression = old is not None and 200 <= old < 400 and (new is not None and new >= 400)
        unknown = old is None or new is None
        rows.append({"path": path, "live": before, "candidate": after, "regression": regression})
        if regression:
            regressions.append(path)
        if unknown:
            unresolved.append(path)
    output = {"live": args.live, "candidate": args.candidate, "rows": rows,
              "regressions": regressions, "unresolved": unresolved,
              "human_redirect_review_required": True}
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Compared {len(rows)} URLs; regressions={len(regressions)}, unreachable={len(unresolved)}")
    print(f"Full HTTP comparison: {args.output}")
    for path in regressions:
        row = next(item for item in rows if item["path"] == path)
        print("REGRESSION {}: live={}, candidate={}".format(path, row["live"]["status"], row["candidate"]["status"]))
    for path in unresolved:
        print(f"UNRESOLVED {path}")
    if regressions or unresolved:
        raise SystemExit("HTTP comparison incomplete or regressions present; not approved for cutover")
    print("No HTTP status regressions in checked candidate set; review redirects and page content manually.")

if __name__ == "__main__":
    main()
