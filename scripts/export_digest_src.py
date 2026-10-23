# -*- coding: utf-8 -*-
r"""
export_digest_src.py — 群刊管线第①步：导出群聊全量文本，按月切片
用途: 产出供 AI 通读提炼的切片文件(每月一个 txt)
用法:
  python export_digest_src.py --group 群名片段 [--db 路径] [--out 切片目录]
输出: <out>\<YYYY-MM>.txt，每行 "DD日 HH:MM 昵称: [标签]正文"
"""
import sqlite3, os, re, sys, argparse
import time as _t

# 统计底座库（wechat_stats.db）：由 Wechat-Memoir 第一阶段（wx_export.py --sqlite）产出。
# 发布版不写默认值 —— 必须用 --db 显式指定（数据与程序分离，跨机器通用）。
DEFAULT_DB = None
TYPE_TAG = {3:"[图片]",34:"[语音]",43:"[视频]",47:"[表情]",48:"[位置]",42:"[名片]"}
PREFIX_RE = re.compile(r"^\[类型\d+\]\s*")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, help="群名片段(需唯一命中)")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="wechat_stats.db 路径（必填；由 Wechat-Memoir 第一阶段（wx_export.py --sqlite）产出）")
    ap.add_argument("--out", default=None, help="切片输出目录, 默认 <db目录>/.workbuddy/digest_src/<群名安全化>/")
    a = ap.parse_args()

    if not a.db:
        sys.exit("[x] 未指定数据库：请用 --db 指向 wechat_stats.db。\n"
                 "    该库由 Wechat-Memoir 第一阶段产出：wx_export.py --group 群名 --sqlite wechat_stats.db")
    if not os.path.isfile(a.db):
        sys.exit(f"[x] 找不到数据库文件: {a.db}\n"
                 "    请先用 wx_export.py --sqlite 生成该库，或检查 --db 路径是否正确。")

    conn = sqlite3.connect(a.db); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT room_id,name FROM groups").fetchall()
    hits = [r for r in rows if a.group in r["name"]]
    if len(hits) != 1:
        sys.exit(f"群名片段『{a.group}』命中 {len(hits)} 个, 需唯一。可选: " + " / ".join(r["name"] for r in rows))
    room, name = hits[0]["room_id"], hits[0]["name"]
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")
    # 审计 D9：--db 是相对路径时 dirname 为空串，切片会落到 CWD 而不是库目录
    db_dir = os.path.dirname(os.path.abspath(a.db))
    out = a.out or os.path.join(db_dir, ".workbuddy", "digest_src", safe)
    os.makedirs(out, exist_ok=True)
    nick = {r["username"]: r["nickname"] for r in conn.execute(
        "SELECT username,nickname FROM members WHERE room_id=?", (room,))}
    msgs = conn.execute(
        "SELECT ts,sender,local_type,is_system,content FROM messages "
        "WHERE room_id=? AND is_system=0 ORDER BY ts", (room,)).fetchall()
    buckets = {}
    for m in msgs:
        lt = _t.localtime(m["ts"]); ym = _t.strftime("%Y-%m", lt)
        nm = nick.get(m["sender"], m["sender"] or "—")
        body = PREFIX_RE.sub("", m["content"] or "").strip() or TYPE_TAG.get(m["local_type"], "[复合消息]")
        tag = "" if m["local_type"] == 1 else TYPE_TAG.get(
            m["local_type"], "[引用]" if m["local_type"] == 244813135921 else "[卡片]")
        buckets.setdefault(ym, []).append(
            f"{lt.tm_mday:02d}日 {lt.tm_hour:02d}:{lt.tm_min:02d} {nm}: {tag}{body}")
    for ym, lines in sorted(buckets.items()):
        p = os.path.join(out, f"{ym}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"【{name} {ym}】共 {len(lines)} 条\n\n" + "\n".join(lines))
        print(p, len(lines), "条", os.path.getsize(p) // 1024, "KB")

if __name__ == "__main__":
    main()
