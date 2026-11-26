"""Run the deploy release read against a stub curl."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "read-release.sh"
REPO = "Living-Proof-Labs/livingproof-evaluator-run"
TAG = "v1.2.3"
TOKEN = "test-token"
PUBLISHED_AT = "2026-11-22T22:26:23Z"
VALID = {
    "tag_name": TAG,
    "draft": False,
    "prerelease": False,
    "published_at": PUBLISHED_AT,
}

CURL_STUB = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["CURL_LOG"])
queue = Path(os.environ["CURL_QUEUE"])
calls = json.loads(log.read_text() or "[]")
calls.append(args)
log.write_text(json.dumps(calls))
items = json.loads(queue.read_text())
if not items:
    sys.stderr.write("curl stub queue is empty\n")
    raise SystemExit(99)
item = items.pop(0)
queue.write_text(json.dumps(items))


def flag(name):
    return args[args.index(name) + 1]


if item.get("exit", 0) != 0:
    if "-w" in args:
        print("000", end="")
    raise SystemExit(item["exit"])

status = str(item["status"])
header = item.get("header", "x-ratelimit-remaining")
lines = [f"HTTP/1.1 {status}"]
if item.get("remaining") is not None:
    lines.append(f"{header}: {item['remaining']}")
Path(flag("-D")).write_text("\r\n".join(lines) + "\r\n\r\n")
Path(flag("-o")).write_text(item.get("body", ""))
if "-w" in args:
    print(status, end="")
"""

SLEEP_STUB = r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path

Path(os.environ["SLEEP_LOG"]).open("a").write(" ".join(sys.argv[1:]) + "\n")
"""


def _response(status, body="", remaining=None, header="x-ratelimit-remaining", exit_code=0):
    return {
        "status": status,
        "body": body,
        "remaining": remaining,
        "header": header,
        "exit": exit_code,
    }


def _run(tmp_path, responses, trace=False):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    sleep = bindir / "sleep"
    curl.write_text(CURL_STUB)
    sleep.write_text(SLEEP_STUB)
    curl.chmod(0o755)
    sleep.chmod(0o755)
    queue = tmp_path / "queue.json"
    call_log = tmp_path / "curl.log"
    sleep_log = tmp_path / "sleep.log"
    queue.write_text(json.dumps(responses))
    call_log.write_text("[]")
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_TOKEN"] = TOKEN
    env["GITHUB_REPOSITORY"] = REPO
    env["RELEASE_TAG"] = TAG
    env["CURL_LOG"] = str(call_log)
    env["CURL_QUEUE"] = str(queue)
    env["SLEEP_LOG"] = str(sleep_log)
    command = ["bash", "-x", str(SCRIPT)] if trace else ["bash", str(SCRIPT)]
    done = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    calls = json.loads(call_log.read_text())
    sleeps = sleep_log.read_text().splitlines() if sleep_log.exists() else []
    return done, calls, sleeps


def _assert_authenticated(calls):
    assert calls, "curl was not called"
    for args in calls:
        headers = [args[index + 1] for index, arg in enumerate(args) if arg == "-H"]
        assert f"Authorization: Bearer {TOKEN}" in headers
        assert "Accept: application/vnd.github+json" in headers
        assert "X-GitHub-Api-Version: 2022-11-28" in headers
        assert args[args.index("--max-time") + 1] == "20"
        assert "-sS" in args
        assert "-f" not in args and "-fsS" not in args
        assert args[-1] == f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
        assert "-D" in args and "-o" in args and "-w" in args


def test_release_read_succeeds_after_two_403s_and_one_published_release(tmp_path):
    responses = [
        _response("403", remaining="2"),
        _response("403", remaining="1"),
        _response("200", body=json.dumps(VALID), remaining="40"),
    ]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 0
    assert done.stdout == ""
    assert len(calls) == 3
    assert sleeps == ["5", "5"]
    _assert_authenticated(calls)


def test_release_read_fails_after_exactly_three_403s(tmp_path):
    responses = [
        _response("403", remaining="2"),
        _response("403", remaining="1"),
        _response("403", remaining="0"),
    ]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 1
    assert len(calls) == 3
    assert sleeps == ["5", "5"]
    assert done.stdout == "release read failed: HTTP 403, x-ratelimit-remaining=0\n"
    _assert_authenticated(calls)


def test_release_read_fails_on_404_after_one_call(tmp_path):
    responses = [
        _response(
            "404", body='{"message":"Not Found"}', remaining="55", header="X-RateLimit-Remaining"
        )
    ]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 1
    assert len(calls) == 1
    assert sleeps == []
    assert done.stdout == "release read failed: HTTP 404, x-ratelimit-remaining=55\n"


def test_release_read_fails_on_draft_release_after_one_call(tmp_path):
    draft = dict(VALID, draft=True)
    done, calls, sleeps = _run(tmp_path, [_response("200", body=json.dumps(draft))])
    assert done.returncode == 1
    assert len(calls) == 1
    assert sleeps == []
    assert done.stdout == "release read failed: HTTP 200, x-ratelimit-remaining=unknown\n"


def test_release_read_fails_closed_on_malformed_json_without_retry(tmp_path):
    done, calls, sleeps = _run(tmp_path, [_response("200", body="not-json", remaining="4")])
    assert done.returncode == 1
    assert len(calls) == 1
    assert sleeps == []
    assert done.stdout == "release read failed: HTTP 200, x-ratelimit-remaining=4\n"


def test_release_read_retries_5xx_then_accepts_a_published_release(tmp_path):
    responses = [
        _response("503", remaining="3"),
        _response("502", remaining="3"),
        _response("200", body=json.dumps(VALID), remaining="3"),
    ]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 0
    assert len(calls) == 3
    assert sleeps == ["5", "5"]


def test_release_read_retries_network_errors_then_accepts(tmp_path):
    responses = [
        {"exit": 28},
        _response("000", remaining="1"),
        _response("200", body=json.dumps(VALID), remaining="9"),
    ]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 0
    assert len(calls) == 3
    assert sleeps == ["5", "5"]
    assert TOKEN not in done.stdout and TOKEN not in done.stderr


def test_release_read_fails_after_three_network_errors(tmp_path):
    responses = [{"exit": 7}, {"exit": 28}, _response("000")]
    done, calls, sleeps = _run(tmp_path, responses)
    assert done.returncode == 1
    assert len(calls) == 3
    assert sleeps == ["5", "5"]
    assert done.stdout == "release read failed: HTTP 000, x-ratelimit-remaining=unknown\n"


def test_release_read_does_not_echo_the_token_when_traced(tmp_path):
    done, calls, _sleeps = _run(tmp_path, [_response("404", remaining="1")], trace=True)
    assert done.returncode == 1
    assert len(calls) == 1
    assert TOKEN not in done.stdout
    assert TOKEN not in done.stderr
