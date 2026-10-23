#!/usr/bin/env python3
"""extract_stocks.py — 从群聊统计库提取 A 股提及时间线（谁·何时·说了什么股票）

数据形态（两种命中，互补）：
  1. 6 位代码：独立数字边界匹配 + 必须在 A 股名单内（60/68/00/30/8/4 开头）
  2. 股票名：≥3 字中文名做子串匹配（名单来自 shdjt.com 全 A 股 js，本地缓存）
     - 名称清洗：剥英文后缀（京东方A→京东方A 保留，屹唐股份 glw→屹唐股份）
     - 泛词警示：机器人/老百姓/同花顺等既是股票名又是日常词 → ambiguous=true 标记

产出（--outdir 下）：
  <群>_股票提及时间线.json   结构化事件流（ts/datetime/code/name/sender/ambiguous/context）
  <群>_股票提及时间线.csv    Excel 可直接开（UTF-8-BOM）

用法：
  python extract_stocks.py --group "群名" --db wechat_stats.db [--outdir ./outputs]
  [--update-names]  重新拉取 A 股名单缓存

名单缓存：~/.workbuddy 同级或脚本同目录 astock_names.json；--update-names 强制刷新。
"""
import argparse
import csv
import datetime
import json
import os
import re
import sqlite3
import urllib.request
from collections import Counter

NAMES_URL = "http://www.shdjt.com/js/lib/astock.js"
AMBIG = {"机器人", "老百姓", "同花顺", "大全", "光大", "中国人保", "工业富联", "上海银行"}


def load_names(cache_path, update=False):
    if not update and os.path.exists(cache_path):
        return json.load(open(cache_path, encoding="utf-8"))
    req = urllib.request.Request(NAMES_URL, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    names = {}
    for code, name in re.findall(r"(\d{6})`([^`~]+)", raw):
        name = re.sub(r"\s*[/\\(（]?[a-zA-Z]{2,8}\s*[)）]?$", "", name).strip()
        names[code] = name
    json.dump(names, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", required=True, help="群名关键词")
    ap.add_argument("--db", required=True, help="wechat_stats.db 路径")
    ap.add_argument("--outdir", default=None, help="输出目录，默认 <db目录>/outputs")
    ap.add_argument("--names-cache", default=None, help="A 股名单缓存路径")
    ap.add_argument("--update-names", action="store_true", help="强制刷新 A 股名单")
    args = ap.parse_args()

    db_dir = os.path.dirname(os.path.abspath(args.db))
    out_dir = args.outdir or os.path.join(db_dir, "outputs")
    cache = args.names_cache or os.path.join(db_dir, ".workbuddy", "astock_names.json")
    os.makedirs(out_dir, exist_ok=True)

    names = load_names(cache, args.update_names)
    code2name = {}
    for code, n in names.items():
        code2name.setdefault(n, code)
    name_set = set(n for n in names.values() if len(n) >= 3)
    print(f"A股名单: {len(names)} 只（缓存 {cache}）")

    con = sqlite3.connect(args.db)
    room = con.execute("SELECT room_id FROM groups WHERE name LIKE ?",
                       (f"%{args.group}%",)).fetchone()
    if not room:
        sys.exit(f"[x] 库中无群「{args.group}」")
    R = room[0]
    nick = {u: n for u, n in con.execute(
        "SELECT username, nickname FROM members WHERE room_id=?", (R,))}

    events = []
    for ts, sender, c in con.execute(
            "SELECT ts, sender, content FROM messages "
            "WHERE room_id=? AND is_system=0 AND local_type=1 ORDER BY ts", (R,)):
        if not c:
            continue
        s = str(c)
        hit = set()
        for m in re.finditer(r"(?<!\d)([0-9]{6})(?!\d)", s):
            code = m.group(1)
            if code in names and (code[:2] in ("60", "68", "00", "30") or code[0] in "84"):
                hit.add(code)
        for n in name_set:
            if n in s:
                hit.add(code2name[n])
        if hit:
            who = nick.get(sender, sender or "?")
            dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            for code in sorted(hit):
                events.append(dict(ts=ts, datetime=dt, code=code, name=names.get(code, "?"),
                                   sender=who, ambiguous=names.get(code, "") in AMBIG,
                                   context=s[:120].replace("\n", " ")))

    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", args.group).strip("_")
    jp = os.path.join(out_dir, f"{safe}_股票提及时间线.json")
    cp = os.path.join(out_dir, f"{safe}_股票提及时间线.csv")
    json.dump(events, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(cp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "datetime", "code", "name",
                                          "sender", "ambiguous", "context"])
        w.writeheader()
        w.writerows(events)

    print(f"提取完成：{len(events)} 条提及 / {len(set(e['code'] for e in events))} 只股票")
    print("\nTop 股票:")
    for (n, c), cnt in Counter((e["name"], e["code"]) for e in events).most_common(10):
        print(f"  {n}({c}): {cnt} 次")
    print("\n提及人分布:")
    for who, cnt in Counter(e["sender"] for e in events).most_common(8):
        print(f"  {who}: {cnt} 次")
    print(f"\n产出:\n  {jp}\n  {cp}")


if __name__ == "__main__":
    main()
