"""Advance a local AI game for a bounded number of rounds, preserving an archive.

This explicitly consumes configured model usage. It talks only to the local
spectator server; it never reads credentials or sends archives to a model.
"""

import argparse
from http.client import IncompleteRead
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def download_archive(base, output):
    """Stream a large local archive; retry transfer only, never game actions."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".archive-download-", dir=output.parent) as directory:
        temporary = Path(directory) / "archive.private.json"
        for attempt in range(2):
            try:
                with urlopen(base + "/api/export", timeout=120) as response, temporary.open("wb") as target:
                    expected = response.headers.get("Content-Length")
                    count = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        count += len(chunk)
                    if expected is not None and count != int(expected):
                        raise OSError("Archive download ended before its declared length.")
                with temporary.open(encoding="utf-8") as source:
                    archive = json.load(source)
                temporary.replace(output)
                return archive
            except (IncompleteRead, OSError, ValueError):
                if attempt:
                    raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--retry-error", action="store_true",
                        help="Explicitly retry the current failed batch once, preserving settings and cached responses.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/live-check.private.json"))
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10 or not 1 <= args.port <= 65535 or args.timeout < 1:
        parser.error("Use 1–10 rounds, a valid local port, and a positive timeout.")
    if not args.output.name.endswith(".private.json"):
        parser.error("Archive path must end in .private.json to remain git-ignored.")
    base = f"http://127.0.0.1:{args.port}"

    def api(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {} if data is None else {"Content-Type": "application/json"}
        with urlopen(Request(base + path, data=data, headers=headers), timeout=30) as response:
            return json.load(response)

    state = api("/api/state")
    if state.get("status") == "error" and args.retry_error:
        print("Explicitly retrying failed decisions once with unchanged player settings.", flush=True)
        api("/api/step", {})
        state = api("/api/state")
    elif state.get("status") == "error":
        parser.exit(1, "Game is paused with an error; resolve it before starting verification.\n")
    initial_day = state["day"]
    target_day = initial_day + args.rounds
    deadline = time.monotonic() + args.timeout
    previous = None
    failed = False
    try:
        while True:
            state = api("/api/state")
            progress = (state["day"], state["phase"], state["step"], state["status"])
            if progress != previous:
                print(json.dumps({"day": state["day"], "phase": state["phase"],
                                  "step": state["step"], "status": state["status"]}), flush=True)
                previous = progress
            if state.get("winner") or state["day"] >= target_day:
                break
            if state.get("status") == "error":
                print(json.dumps({"error": state.get("error")}), flush=True)
                failed = True
                break
            if time.monotonic() >= deadline:
                print("Verification time limit reached; preserving the current game.", flush=True)
                failed = True
                break
            if not state.get("busy") and not state.get("playing"):
                try:
                    api("/api/step", {})
                except HTTPError as exc:
                    if exc.code != 409:
                        raise
            time.sleep(0.5)
    except KeyboardInterrupt:
        failed = True
        print("Verification interrupted; preserving the current game.", flush=True)
    finally:
        api("/api/pause", {})
        # Pause respects atomic in-flight batches. Wait for that one batch only.
        while api("/api/state").get("busy"):
            time.sleep(0.5)
        archive = download_archive(base, args.output)
        records = archive.get("inference", [])
        print(json.dumps({"archive": str(args.output), "requests": len(records),
                          "accepted": sum(bool(r.get("accepted")) for r in records),
                          "rejected": sum(bool(r.get("error")) for r in records),
                          "winner": archive["game"].get("winner")}), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
