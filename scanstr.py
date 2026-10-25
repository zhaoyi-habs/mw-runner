#!/usr/bin/env python3
"""扫描 APK 内二进制里的中文字符串，找出模型导入相关入口。"""
import re, sys, subprocess, os

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/apkx/lib/arm64-v8a/liblibGameApp.so"
KEYS = ["导入", "模型", "资源库", "外部", "FBX", "fbx", "obj", "omod"]

CJK = re.compile(rb'(?:[\xe4-\xe9][\x80-\xbf][\x80-\xbf]|[\x20-\x7e]){4,120}')

hits = {}
with open(PATH, "rb") as f:
    prev = b""
    while True:
        buf = f.read(8 << 20)
        if not buf:
            break
        data = prev + buf
        for m in CJK.finditer(data):
            try:
                s = m.group().decode("utf-8")
            except Exception:
                continue
            if not any("\u4e00" <= c <= "\u9fff" for c in s):
                continue
            for k in KEYS:
                if k in s:
                    hits.setdefault(k, set()).add(s)
        prev = data[-256:]

for k in KEYS:
    v = sorted(hits.get(k, []))
    print(f"\n===== {k} ({len(v)}) =====")
    for s in v[:60]:
        print(" ", s)
