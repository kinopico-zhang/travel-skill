#!/usr/bin/env python3
"""Dump mitmproxy flow file: index, time, method, URL (optional: with bodies)."""
import sys
from datetime import datetime
from mitmproxy import http as mhttp, io

path = sys.argv[1]
start = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
show_body = "-b" in sys.argv

with open(path, "rb") as f:
    for i, fl in enumerate(io.FlowReader(f).stream()):
        if not isinstance(fl, mhttp.HTTPFlow) or i < start:
            continue
        ts = datetime.fromtimestamp(fl.timestamp_start).strftime("%H:%M:%S")
        r = fl.request
        status = fl.response.status_code if fl.response else "?"
        print(f"[{i}] {ts} {r.method} {status} {r.pretty_url}")
        if not show_body:
            continue
        try:
            if r.raw_content:
                body = r.content if r.content else r.raw_content
                print(f"    REQ: {body[:2000].decode('utf-8', 'replace')}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"    REQ-ERR: {e}")
        try:
            rsp = getattr(fl, "response", None)
            if rsp is not None and rsp.raw_content:
                body = rsp.content if rsp.content else rsp.raw_content
                print(f"    RSP: {body[:2000].decode('utf-8', 'replace')}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"    RSP-ERR: {e}")
