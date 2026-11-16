#!/usr/bin/env python3
"""Backup waker: wake the box, start the hour's x-feed round if box's own schedule missed it,
then disconnect. If this hour already has a summary the box skips the round in seconds;
either way the round hibernates the box when it ends (it is billed per hour awake).

Runs on GitHub Actions (or any always-on machine). Needs env BOX_TOKEN: a personal key
from https://box.simular.ai/access. Optional BOX_ID (default: your default box).
Exit: 0 round succeeded or was skipped · 1 round failed · 2 could not reach box.
"""
import json, os, sys, time, urllib.request, urllib.error

URL = os.environ.get("BOX_MCP_URL", "https://mcp.box.simular.ai/mcp")
TOKEN = os.environ.get("BOX_TOKEN", "")
BOX = os.environ.get("BOX_ID", "")

if not TOKEN:
    sys.exit("BOX_TOKEN is not set")

session, rid = None, 0

def rpc(method, params=None, notify=False):
    """One JSON-RPC call over MCP streamable HTTP (handles JSON or SSE replies)."""
    global session, rid
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None: msg["params"] = params
    if not notify: rid += 1; msg["id"] = rid
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "Authorization": "Bearer " + TOKEN, "MCP-Protocol-Version": "2025-06-18"}
    if session: h["Mcp-Session-Id"] = session
    req = urllib.request.Request(URL, json.dumps(msg).encode(), h)
    with urllib.request.urlopen(req, timeout=180) as r:
        session = r.headers.get("Mcp-Session-Id") or session
        body = r.read().decode("utf-8", "replace")
        ctype = r.headers.get("Content-Type", "")
    if notify or not body.strip(): return None
    if "event-stream" in ctype:   # take the last data: line that carries our id
        out = None
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    d = json.loads(line[5:].strip())
                    if d.get("id") == msg["id"]: out = d
                except json.JSONDecodeError: pass
        body_obj = out
    else:
        body_obj = json.loads(body)
    if not body_obj: raise RuntimeError(f"{method}: empty reply")
    if "error" in body_obj: raise RuntimeError(f"{method}: {body_obj['error']}")
    return body_obj["result"]

def shell(cmd, timeout_s=60):
    args = {"command": cmd, "timeout_s": timeout_s}
    if BOX: args["box"] = BOX
    res = rpc("tools/call", {"name": "shell", "arguments": args})
    text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    return text.strip()

def main():
    try:
        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "xfeed-waker", "version": "1"}})
        rpc("notifications/initialized", notify=True)
        print("box:", shell("TZ=Etc/GMT+5 date '+awake %F %H:%M MBT'; systemctl --user is-active xfeed.service"))
    except Exception as e:
        print("could not reach box:", e); return 2

    # Start the hour's round and leave. Polling would keep the box awake (it is billed by the hour)
    # and would wake it again right after the round hibernates it. The round itself skips if this
    # hour already has a summary, and hibernates the box when it is done.
    print(shell("systemctl --user start --no-block xfeed.service && echo started"))
    return 0

if __name__ == "__main__":
    sys.exit(main())
