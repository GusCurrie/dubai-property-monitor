#!/usr/bin/env python3
"""Splice the compressed data payload into the dashboard template -> docs/index.html"""
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tpl = open(os.path.join(ROOT, "docs", "template.html")).read()
payload = open(os.path.join(ROOT, "docs", "payload.b64")).read().strip()
html = tpl.replace("__PAYLOAD_B64__", payload)
with open(os.path.join(ROOT, "docs", "index.html"), "w") as f:
    f.write(html)
print(f"index.html written ({len(html)//1024} KB)")
