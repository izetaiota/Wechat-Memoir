# -*- coding: utf-8 -*-
r"""make_persona_src.py — 为人物判词/时间胶囊导原料
用法: python make_persona_src.py [群名片段] --db <wechat_stats.db>   (缺省片段 "127")
输出(位于 DB 同级的 .workbuddy/digest_src/<群名安全化>/personas/):
  <安全昵称>.txt   Top10 每人全部文本消息(按时间)
  _anchors.md      高光锚点(首末消息/最长/深夜/峰值日/每人首末句)
"""
import sqlite3, os, re, sys, datetime, time as _t, argparse

parser = argparse.ArgumentParser(description="为人物判词/时间胶囊导原料")
parser.add_argument("group", nargs="?", default="127", help="群名片段 (缺省 127)")
parser.add_argument("--db", required=True, help="wechat_stats.db 路径")
_args = parser.parse_args()
DB = _args.db
GROUP_FRAG = _args.group
PREFIX_RE = re.compile(r"^\[类型\d+\]\s*")

conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT room_id,name FROM groups").fetchall()
hits = [r for r in rows if GROUP_FRAG in r["name"]]
assert len(hits) == 1, f"群片段 {GROUP_FRAG} 命中 {len(hits)} 个"
room, name = hits[0]["room_id"], hits[0]["name"]

msgs = conn.execute(
    "SELECT ts,sender,local_type,is_system,content FROM messages WHERE room_id=? AND is_system=0 ORDER BY ts",
    (room,)).fetchall()
nick2user = {}
for r in conn.execute("SELECT username,nickname FROM members WHERE room_id=?", (room,)):
    nick2user.setdefault(r["nickname"], []).append(r["username"])
nick_of = {r["username"]: r["nickname"] for r in
           conn.execute("SELECT username,nickname FROM members WHERE room_id=?", (room,))}

def body(m):
    if m["local_type"] != 1: return None
    b = PREFIX_RE.sub("", m["content"] or "").strip()
    return b or None

by_sender = {}
for m in msgs:
    if m["sender"]: by_sender[m["sender"]] = by_sender.get(m["sender"], 0) + 1
top10 = sorted(by_sender.items(), key=lambda x: -x[1])[:10]

safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")
out_dir = os.path.join(os.path.dirname(DB), ".workbuddy", "digest_src", safe_name, "personas")
os.makedirs(out_dir, exist_ok=True)
chat_msgs = [m for m in msgs if body(m)]

# ---- 每人切片 + 首末句 ----
firstlast = []
for user, cnt in top10:
    nick = nick_of.get(user, user)
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", nick).strip("_") or f"u{user}"
    path = os.path.join(out_dir, f"{safe}.txt")
    lines = []
    for m in msgs:
        if m["sender"] != user: continue
        b = body(m)
        if b is None: continue
        lt = _t.localtime(m["ts"])
        lines.append(f"{_t.strftime('%m-%d %H:%M', lt)} {b}")
    if not lines: continue
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    firstlast.append((nick, cnt, len(lines), lines[0][:120], lines[-1][:120]))
    print(f"{safe}.txt  {len(lines)} 条  {os.path.getsize(path)//1024}KB")

# ---- 锚点 ----
A = [f"# 高光锚点 · {name}", ""]
A.append(f"第一条消息: {chat_msgs[0]['ts']} {nick_of.get(chat_msgs[0]['sender'],'?')}: {body(chat_msgs[0])[:200]}")
A.append(f"最后一条消息: {nick_of.get(chat_msgs[-1]['sender'],'?')}: {body(chat_msgs[-1])[:200]}")
longs = sorted(chat_msgs, key=lambda m: -len(body(m)))[:6]
A.append("\n## 最长的 6 条")
for m in longs:
    A.append(f"- {_t.strftime('%m-%d %H:%M', _t.localtime(m['ts']))} {nick_of.get(m['sender'],'?')} ({len(body(m))}字): {body(m)[:300]}")
night = [m for m in chat_msgs if 0 <= _t.localtime(m["ts"]).tm_hour < 5]
A.append(f"\n## 深夜消息(0~5点): 共 {len(night)} 条")
for m in sorted(night, key=lambda m: -len(body(m) or ""))[:5]:
    A.append(f"- {_t.strftime('%m-%d %H:%M', _t.localtime(m['ts']))} {nick_of.get(m['sender'],'?')}: {body(m)[:200]}")
daily = {}
for m in msgs: daily[_t.strftime('%Y-%m-%d', _t.localtime(m["ts"]))] = daily.get(_t.strftime('%Y-%m-%d', _t.localtime(m["ts"])), 0) + 1
peak = max(daily, key=daily.get)
pk_senders = {}
for m in msgs:
    d = _t.strftime('%Y-%m-%d', _t.localtime(m["ts"]))
    if d == peak and m["sender"]: pk_senders[m["sender"]] = pk_senders.get(m["sender"], 0) + 1
A.append(f"\n峰值日 {peak} 共 {daily[peak]} 条, 当日最活跃: " +
         " / ".join(f"{nick_of.get(u,u)}:{c}" for u, c in sorted(pk_senders.items(), key=lambda x: -x[1])[:3]))
A.append("\n## Top10 每人第一句 / 最后一句")
for nick, cnt, n, first, last in firstlast:
    A.append(f"### {nick} (总 {cnt} 条, 文本 {n} 条)\n- 首句: {first}\n- 末句: {last}")
with open(os.path.join(out_dir, "_anchors.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(A))
print("\n锚点文件:", os.path.join(out_dir, "_anchors.md"))
