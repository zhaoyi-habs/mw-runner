#!/usr/bin/env python3
"""上传已存在的本地 PNG（快速取证用）。用法: python3 shotup.py <本地png> <tag>"""
import os, sys, json, time, base64, urllib.request, urllib.error

TOKEN = os.environ["GH_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
BR = "main"
CH = 90_000
SRC = sys.argv[1]
TAG = sys.argv[2] if len(sys.argv) > 2 else "x"


def api(path, method="GET", data=None, ref=BR):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    if method == "GET":
        url += f"?ref={ref}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("User-Agent", "shotup")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 304):
            return None
        raise


def put(path, content, tries=8):
    for i in range(tries):
        try:
            body = {"message": "su " + path, "branch": BR,
                    "content": base64.b64encode(content.encode()).decode()}
            old = api(path)
            if old:
                body["sha"] = old["sha"]
            r = api(path, "PUT", body)
            if isinstance(r, dict) and r.get("content", {}).get("sha"):
                return True
        except Exception:
            pass
        time.sleep(1.2 * (i + 1))
    return False


d = open(SRC, "rb").read()
if d[:4] != b"\x89PNG":
    print("SHOT_FAIL not png", len(d))
    raise SystemExit(1)

raw = base64.b64encode(d).decode()
n = (len(raw) + CH - 1) // CH
stamp = f"{int(time.time())}_{TAG}"
files, bad = [], []
for i in range(n):
    f = f"relay/q_{stamp}_{i}.b64"
    if put(f, raw[i * CH:(i + 1) * CH]):
        files.append(f)
    else:
        bad.append(f)
if bad:
    print("SHOT_FAIL chunks", len(bad))
    raise SystemExit(1)
meta = {"files": files, "bytes": len(d), "stamp": stamp}
if not put("relay/q_meta.json", json.dumps(meta)):
    print("SHOT_FAIL meta")
    raise SystemExit(1)
print(f"SHOT_OK {len(d)}B {n}chunks {stamp}")
