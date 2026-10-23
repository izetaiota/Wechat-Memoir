# -*- coding: utf-8 -*-
r"""
render_group_page.py — 单群"群刊"生成器（纸刊风）· 管线第③步
数据源: wechat_stats.db（来自 Wechat-Memoir 第一阶段）
前置: 编辑部稿 <workdir>\<群名安全化>_digest.json 必须存在（AI 通读切片后写就），缺失即拒渲染
设计借鉴: 豆包 chat-digest（纸质感/章节式目录/语录卡/渐入动画）
用法:
  python render_group_page.py --group 群名片段 [--db 路径] [--out x.html] [--workdir insights目录]
"""
import sqlite3, json, html, sys, os, re, argparse
import time as _t
import datetime as _dt
from collections import defaultdict

# 统计底座库（wechat_stats.db）：由 Wechat-Memoir 第一阶段（wx_export.py --sqlite）产出。
# 发布版不写默认值 —— 必须用 --db 显式指定（数据与程序分离，跨机器通用）。
DEFAULT_DB = None
PREFIX_RE = re.compile(r"^\[类型\d+\]\s*")

def esc(s): return html.escape(s or "", quote=True)

def fetch_room(conn, frag):
    rows = conn.execute("SELECT room_id,name FROM groups").fetchall()
    hits = [r for r in rows if frag in r["name"]] if frag else rows
    if len(hits) != 1:
        names = " / ".join(r["name"] for r in rows)
        sys.exit(f"群名片段『{frag}』命中 {len(hits)} 个,需唯一。可选: {names}")
    return hits[0]["room_id"], hits[0]["name"]

# ---------- 数据 ----------
def load(conn, room):
    g = conn.execute("SELECT * FROM groups WHERE room_id=?", (room,)).fetchone()
    msgs = conn.execute(
        "SELECT ts,sender,local_type,is_system,content FROM messages WHERE room_id=? ORDER BY ts",
        (room,)).fetchall()
    nick = {r["username"]: r["nickname"] for r in conn.execute(
        "SELECT username,nickname FROM members WHERE room_id=?", (room,))}
    # 媒体索引（Roadmap 1.3-1.5）：表可缺省（老库无 media 表 = 无媒体版块）
    media = []
    try:
        media = conn.execute(
            "SELECT ts,sender,media_type,file_name,file_size,duration_ms,md5,local_path "
            "FROM media WHERE room_id=? ORDER BY ts", (room,)).fetchall()
    except Exception:
        pass
    return g, msgs, nick, media

def compute(g, msgs, nick):
    chat = [m for m in msgs if not m["is_system"]]
    daily = defaultdict(int)
    by_sender = defaultdict(int); longs = []
    for m in msgs:
        lt = _t.localtime(m["ts"]); d = _t.strftime("%Y-%m-%d", lt)
        if m["is_system"]:
            continue
        daily[d] += 1
        if m["sender"]: by_sender[m["sender"]] += 1
        if m["local_type"] == 1:
            body = PREFIX_RE.sub("", m["content"] or "").strip()
            if len(body) >= 100:
                longs.append(dict(day=d, tm=_t.strftime("%H:%M", lt), sender=m["sender"],
                                  nick=nick.get(m["sender"], m["sender"] or "—"),
                                  body=body, len=len(body)))
    days = sorted(daily)
    speakers = len([s for s in by_sender if s])
    total = len(chat)
    if not days:
        # 审计 D2：空群/全是系统消息的群，原来在下一行 days[0] 直接 IndexError
        sys.exit("[x] 该群在统计库里没有有效聊天消息，无法渲染群刊。\n"
                 "    常见原因：该群只导出了系统/撤回/拍一拍消息，或尚未把该群导入 wechat_stats.db。")
    d0, d1 = days[0], days[-1]
    span_days = (_dt.date(int(d1[:4]), int(d1[5:7]), int(d1[8:10]))
                 - _dt.date(int(d0[:4]), int(d0[5:7]), int(d0[8:10]))).days + 1
    top_pool = sorted(by_sender.items(), key=lambda x: -x[1])[:24]
    return dict(g=g, nick=nick, daily=dict(daily),
                longs=longs, speakers=speakers, total=total, d0=d0, d1=d1, span_days=span_days,
                top_pool=top_pool)

# ---------- 图表(SVG, 纸刊配色) ----------
def svg_bars(daily, W=980, H=210):
    days = sorted(daily); mx = max(daily.values()) or 1
    n = len(days); bw = W / n
    peak_day = max(daily, key=lambda k: daily[k])
    parts = []
    for i, d in enumerate(days):
        h = daily[d] / mx * (H - 40)
        color, extra = "#3D5C4C", ""
        if d == peak_day:
            color, extra = "#A63D24", f'<text x="{i*bw+bw/2:.1f}" y="{H-24-h:.1f}" text-anchor="middle" fill="#A63D24" font-size="11" font-weight="700">{daily[d]}</text>'
        parts.append(f'<rect x="{i*bw:.1f}" y="{H-22-h:.1f}" width="{max(bw-1.6,1):.1f}" height="{h:.1f}" rx="2.5" fill="{color}"><title>{d} · {daily[d]} 条</title></rect>{extra}')
        if i == 0 or days[i-1][5:7] != d[5:7]:
            parts.append(f'<text x="{i*bw:.1f}" y="{H-5}" class="ax">{int(d[5:7])}月</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart">' + "".join(parts) + "</svg>"

# ---------- 内容组装 ----------
# ---------- 话题地图(SVG 力导向布局, 数据来自 digest.graph) ----------
def graph_svg(graph, W=980, H=540):
    """话题地图：Python 算确定性初始布局，前端 JS 接管力导向 + 拖拽（数据来自 digest.graph）"""
    import math, random
    nodes = graph["nodes"]; edges = graph["edges"]
    groups = graph.get("groups", {})
    color = {gid: g.get("color", "#3D5C4C") for gid, g in groups.items()}
    label = {gid: g.get("label", gid) for gid, g in groups.items()}
    rnd = random.Random(42)
    pos = {n["id"]: [rnd.uniform(160, W-160), rnd.uniform(90, H-90)] for n in nodes}
    # 审计 D3：digest.json 是手写/AI 写的，边的端点可能拼错。先过滤非法边并告警，
    # 否则下面 pos[e["a"]] 会直接 KeyError（JS 端虽有过滤，但 Python 布局先崩）。
    n_edge_all = len(edges)
    edges = [e for e in edges if e.get("a") in pos and e.get("b") in pos]
    if len(edges) != n_edge_all:
        print(f"[!] 图谱告警: 忽略 {n_edge_all - len(edges)} 条引用不存在节点的边"
              f"（端点 id 与 nodes[].id 不一致，请检查 digest.json 的 graph.edges）")
    for _ in range(420):
        ns = list(pos.items())
        for i, (ai, pa) in enumerate(ns):
            for bi, pb in ns[i+1:]:
                dx, dy = pa[0]-pb[0], pa[1]-pb[1]
                d2 = dx*dx + dy*dy + 120
                f = 5200 / d2
                d = math.sqrt(d2)
                fx, fy = dx/d*f, dy/d*f
                pa[0] += fx; pa[1] += fy; pb[0] -= fx; pb[1] -= fy
        for e in edges:
            pa, pb = pos[e["a"]], pos[e["b"]]
            dx, dy = pb[0]-pa[0], pb[1]-pa[1]
            d = math.sqrt(dx*dx + dy*dy) or 1
            f = (d - 165) * 0.018
            fx, fy = dx/d*f, dy/d*f
            pa[0] += fx; pa[1] += fy; pb[0] -= fx; pb[1] -= fy
        for p in pos.values():
            p[0] += (W/2 - p[0]) * 0.012; p[1] += (H/2 - p[1]) * 0.012
            p[0] = max(85, min(W-85, p[0])); p[1] = max(52, min(H-38, p[1]))
    byid = {n["id"]: n for n in nodes}
    # 关系配色只留三类：因果(朱砂实线) / 解法替代(墨绿) / 其余(灰虚线)
    REL = {"导致": ("#A63D24", "1.7", ""), "解法": ("#3D5C4C", "1.6", ""),
           "替代": ("#3D5C4C", "1.3", "5,4"), "案例": ("#8C8272", "1.3", "2,3")}
    lines = []
    for e in edges:
        pa, pb = pos[e["a"]], pos[e["b"]]
        rel = e.get("rel", "")
        rc, rw, rd = REL.get(rel, ("#B3A995", "1.2", "5,4"))
        dash = f' stroke-dasharray="{rd}"' if rd else ""
        ta, tb = byid.get(e["a"], {}).get("label", ""), byid.get(e["b"], {}).get("label", "")
        tip = f'{ta} —{rel}→ {tb}' if rel else f'{ta} — {tb}'
        lines.append(f'<line class="gedge" x1="{pa[0]:.1f}" y1="{pa[1]:.1f}" x2="{pb[0]:.1f}" y2="{pb[1]:.1f}" '
                     f'stroke="{rc}" stroke-width="{rw}" opacity=".55"{dash}><title>{esc(tip)}</title></line>')
    gdata_nodes = []
    for n in nodes:
        x, y = pos[n["id"]]
        r = 11 + n.get("w", 2) * 3.6
        c = color.get(n.get("g", ""), "#3D5C4C")
        tip = f'{n["label"]}（{label.get(n.get("g",""),"")}）'
        lines.append(f'<g class="gnode" data-id="{esc(n["id"])}"><title>{esc(tip)}</title>'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{c}" fill-opacity=".14" stroke="{c}" stroke-width="1.6"/>'
                     f'<text x="{x:.1f}" y="{y+r+15:.1f}" text-anchor="middle">{esc(n["label"])}</text></g>')
        gdata_nodes.append(dict(id=n["id"], x=round(x, 1), y=round(y, 1), r=round(r, 1)))
    legend = "".join(f'<span><i style="background:{color[gid]}"></i>{esc(lb)}</span>' for gid, lb in label.items())
    payload = json.dumps(dict(W=W, H=H, nodes=gdata_nodes,
                              edges=[dict(a=e["a"], b=e["b"]) for e in edges]),
                         ensure_ascii=False).replace("<", "\\u003c")
    return (f'<div class="glegend">{legend}<span class="ghint">拖动节点可重新排布 · 悬停看关系</span></div>'
            f'<svg id="topic-graph" viewBox="0 0 {W} {H}" class="chart">' + "".join(lines) + "</svg>"
            f'<script type="application/json" id="graph-data">{payload}</script>')

def cheat_table(tb):
    """章节速查表：数据来自 digest.themes[].table（AI 提炼的结构化知识）"""
    if not tb or not tb.get("rows"):
        return ""
    cols = "".join(f"<th>{esc(c)}</th>" for c in tb["cols"])
    rows = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in tb["rows"])
    return (f'<div class="table-card cheat reveal"><div class="tc-head">{esc(tb.get("caption", "速查表"))}</div>'
            f'<div class="table-wrap"><table><thead><tr>{cols}</tr></thead><tbody>{rows}</tbody></table></div></div>')

def tag_chips(tags):
    if not tags:
        return ""
    t = tags if isinstance(tags, list) else [tags]
    return '<div class="e-tags">' + "".join(
        f'<span class="e-tag{" t2" if i else ""}">{esc(x)}</span>' for i, x in enumerate(t)) + "</div>"

def theme_section(th, cn):
    items = "".join(
        f'<article class="entry reveal"><div class="e-head"><span class="e-no">{it["no"]}</span>'
        f'<h3>{esc(it["title"])}</h3>{tag_chips(it.get("tag", ""))}</div>'
        f'<p class="e-meta">出处 {esc(it.get("source", ""))}'
        + (f'<span class="e-conf{" hot" if "争议" in it.get("confidence", "") else ""}">'
           f'{esc(it.get("confidence", ""))}</span>' if it.get("confidence") else "")
        + f'</p>{it["body_html"]}</article>'
        for it in th["items"])
    return (f'<section class="ch" id="{th["id"]}"><div class="ch-head reveal">'
            f'<div class="ch-index"><span class="cn">{cn}</span>'
            f'<span class="meta">{esc(th.get("meta", ""))}</span></div>'
            f'<h2>{esc(th["title"])}</h2><p class="lead">{th["lead"]}</p><div class="rule"></div></div>'
            f'{cheat_table(th.get("table"))}{items}</section>')

def quote_cards(quotes):
    return "".join(
        f'<div class="quote reveal"><div class="q-txt">{esc(q["text"])}</div>'
        f'<div class="q-who">{esc(q["who"])} · {esc(q["date"])}</div></div>'
        for q in quotes)

CSS = """
:root{--paper:#F7F4EC;--paper-2:#FCFAF5;--surface:#FFFEFB;--ink:#2B251C;--body:#4A4236;
--muted:#8C8272;--faint:#A1977F;--hair:#E6DFD0;--hair-2:#F0EBDF;--jade:#3D5C4C;--jade-deep:#2C4338;
--jade-soft:#EAEFE9;--cinnabar:#A63D24;--cinnabar-soft:#F5EBE5;
--sys:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
--serif:"Noto Serif SC","Songti SC","SimSun",serif;--sans:var(--sys)}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;overflow-x:hidden}
body{background:var(--paper);color:var(--body);font-family:var(--sys);font-size:16px;line-height:1.9;-webkit-font-smoothing:antialiased;overflow-x:hidden}
/* 审计 D5：overflow-x:hidden 会把 html/body 变成滚动容器，使 position:sticky 失效（目录不吸顶）。
   clip 同样裁掉横向溢出但不产生滚动容器 -> sticky 正常。旧浏览器不支持 clip 时自动回退 hidden。 */
@supports (overflow-x:clip){html{overflow-x:clip}body{overflow-x:clip}}
p,li{text-wrap:pretty}
.stats .num,.pct,.cap .d,.e-meta,.cc-sub{font-variant-numeric:tabular-nums}
a:focus-visible,summary:focus-visible{outline:2px solid var(--cinnabar);outline-offset:3px;border-radius:2px}
::selection{background:var(--cinnabar);color:#fff}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
background:radial-gradient(1200px 600px at 85% -10%,rgba(214,197,168,.22),transparent 60%),
radial-gradient(900px 500px at -10% 30%,rgba(186,203,186,.16),transparent 55%)}
.wrap{position:relative;z-index:1;max-width:1000px;margin:0 auto;padding:0 28px}
.hero{padding:84px 0 40px;position:relative}
.kicker{display:flex;justify-content:space-between;align-items:baseline;font-family:var(--sans);font-size:12px;letter-spacing:.35em;color:var(--muted);border-top:1px solid var(--ink);padding-top:14px}
.kicker b{color:var(--cinnabar);font-weight:500}
.hero-row{display:flex;align-items:flex-start;justify-content:space-between;gap:36px;margin-top:44px}
.hero h1{font-size:clamp(32px,4.8vw,52px);font-weight:900;color:var(--ink);line-height:1.22;letter-spacing:.04em;word-break:keep-all;text-wrap:balance}
.hero h1 .en{display:block;font-family:var(--sans);font-weight:300;font-size:.32em;letter-spacing:.5em;color:var(--muted);margin-top:18px;text-transform:uppercase}
.seal{flex:none;width:96px;height:96px;margin-top:8px;transform:rotate(-7deg);background:linear-gradient(150deg,var(--cinnabar),#8F2E18);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:var(--serif);font-weight:700;font-size:32px;line-height:1.15;box-shadow:0 10px 26px rgba(140,45,20,.28),inset 0 0 0 3px rgba(255,255,255,.22);border-radius:6px}
.seal small{font-size:11px;letter-spacing:.4em;font-weight:400;margin-top:2px}
.lede{margin-top:36px;max-width:760px;font-size:16.5px;color:var(--body);line-height:2.05}
.lede em{font-style:normal;color:var(--cinnabar);font-weight:600}
.stats{margin-top:44px;display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--hair);background:var(--surface);border-radius:10px}
.stats .cell{padding:22px 26px;border-right:1px solid var(--hair-2)}
.stats .cell:last-child{border-right:none}
.stats .num{font-family:var(--sans);font-size:32px;font-weight:700;color:var(--ink);line-height:1.1}
.stats .num i{font-style:normal;font-size:17px;color:var(--muted);font-weight:400;margin-left:2px}
.stats .lbl{font-size:12.5px;color:var(--muted);margin-top:6px;font-family:var(--sans);letter-spacing:.14em}
.stats .cell.hot .num{color:var(--cinnabar)}
.chart-card{margin-top:26px;background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:26px 26px 14px}
.cc-head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}
.cc-title{font-size:15px;color:var(--ink);font-weight:700}
.cc-sub{font-size:12px;color:var(--muted);font-family:var(--sans)}
.chart{width:100%;height:auto;display:block}
.ax{font-size:11px;fill:#A1977F;font-family:var(--sans)}
.toc{position:sticky;top:0;z-index:50;margin:56px -28px 0;background:rgba(245,240,229,.94);backdrop-filter:blur(8px);border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
.toc-inner{max-width:1000px;margin:0 auto;padding:13px 28px;display:flex;gap:8px 24px;flex-wrap:wrap}
.toc a{font-family:var(--sans);font-size:13px;color:var(--muted);text-decoration:none;letter-spacing:.06em;padding:4px 2px;position:relative;white-space:nowrap;transition:color .25s cubic-bezier(.25,1,.5,1)}
.toc a:hover{color:var(--ink)}
.toc a.active{color:var(--cinnabar);font-weight:500}
.toc a.active::after{content:"";position:absolute;left:0;right:0;bottom:-13px;height:2px;background:var(--cinnabar)}
section.ch{padding:72px 0 8px;scroll-margin-top:64px}
.ch-head{margin-bottom:40px}
.ch-index{display:flex;align-items:center;gap:18px}
.ch-index .cn{font-family:var(--serif);font-size:52px;font-weight:900;color:var(--jade-soft);-webkit-text-stroke:1.2px var(--jade);opacity:.9;line-height:1}
.ch-index .meta{font-family:var(--sans);font-size:11px;letter-spacing:.42em;color:var(--muted);text-transform:uppercase}
.ch h2{font-size:clamp(24px,3.2vw,32px);color:var(--ink);font-weight:900;margin-top:14px;letter-spacing:.03em;text-wrap:balance}
.ch .lead{margin-top:16px;max-width:780px;color:var(--body);font-size:15.5px}
.ch .lead b{color:var(--jade-deep);font-weight:700}
.rule{width:100%;height:1px;background:linear-gradient(90deg,var(--hair) 0 82%,transparent);margin:32px 0 8px}
.graph-card{margin-top:26px;background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:20px 24px 12px}
.glegend{display:flex;gap:20px;flex-wrap:wrap;align-items:center;font-family:var(--sans);font-size:12px;color:var(--muted);padding:2px 4px 10px}
.glegend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.ghint{margin-left:auto;font-size:11.5px;color:var(--faint);letter-spacing:.06em}
.gnode{cursor:grab;user-select:none;transition:opacity .2s}
.gnode:active{cursor:grabbing}
.gnode circle{transition:stroke-width .25s}
.gnode text{font-family:var(--sans);font-size:12px;fill:#4A4236;transition:font-weight .15s}
.gnode:hover text{font-weight:700;fill:#2B251C}
.gedge{transition:opacity .2s,stroke-width .2s}
.focusing .gnode{opacity:.22}
.focusing .gnode.on{opacity:1}
.focusing .gnode.on circle{stroke-width:3.4}
.focusing .gedge{opacity:.08}
.focusing .gedge.on{opacity:.95;stroke-width:2.4}
.table-card{background:var(--surface);border:1px solid var(--hair);border-radius:10px;overflow:hidden;margin:0 0 16px}
.tc-head{font-size:14px;font-weight:700;color:var(--ink);padding:18px 26px 0;font-family:var(--sans);letter-spacing:.08em}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
table{width:100%;border-collapse:collapse}
th,td{padding:13px 22px;text-align:left;vertical-align:top;font-size:13.5px;line-height:1.8}
thead th{font-family:var(--sans);font-size:12px;letter-spacing:.18em;color:var(--muted);font-weight:500;border-bottom:1px solid var(--ink);white-space:nowrap}
tbody tr{border-bottom:1px solid var(--hair-2)}
tbody tr:last-child{border-bottom:none}
td .bar{display:inline-block;height:10px;border-radius:4px;background:var(--jade);vertical-align:middle;margin-right:10px}
td .bar.top{background:var(--cinnabar)}
td .pct{font-family:var(--sans);color:var(--muted);font-size:12px}
.entry{background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:24px 28px;margin-bottom:14px;transition:border-color .3s cubic-bezier(.25,1,.5,1),transform .3s cubic-bezier(.25,1,.5,1),box-shadow .3s cubic-bezier(.25,1,.5,1)}
.entry:hover{border-color:#CDBF9F;box-shadow:0 12px 30px rgba(120,104,70,.08);transform:translateY(-2px)}
.e-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.e-no{flex:none;font-family:var(--sans);font-size:12px;font-weight:700;color:var(--surface);background:var(--jade);border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;transform:translateY(2px)}
.entry h3{font-size:16.5px;color:var(--ink);font-weight:700;letter-spacing:.02em}
.e-tags{margin-left:auto;display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}
.e-tag{font-family:var(--sans);font-size:11px;color:var(--muted);border:1px solid var(--hair);background:var(--paper-2);padding:1px 9px;border-radius:99px;white-space:nowrap}
.e-tag.t2{color:var(--faint);background:transparent;border-color:var(--hair-2)}
.e-meta{font-family:var(--sans);font-size:12px;color:var(--faint);margin:2px 0 8px;letter-spacing:.08em;display:flex;gap:14px;flex-wrap:wrap;align-items:baseline}
.e-conf{font-size:11px;color:var(--muted)}
.e-conf.hot{color:var(--cinnabar)}
.entry ul{margin:6px 0 2px;padding-left:18px}
.entry li{font-size:14.5px;line-height:1.95;color:var(--body);margin-bottom:4px;list-style:none;position:relative}
.entry li::before{content:"";position:absolute;left:-14px;top:12px;width:5px;height:5px;border-radius:50%;background:var(--jade);opacity:.5}
.entry li b{color:var(--ink);font-weight:700}
.cheat{margin:0 0 16px}
.cheat table td{font-size:13px;line-height:1.75;padding:11px 18px}
.cheat thead th{font-size:11.5px}
.entry details{margin-top:4px}
.entry details summary{font-family:var(--sans);font-size:12.5px;color:var(--jade);cursor:pointer;letter-spacing:.1em;user-select:none;transition:color .2s}
.entry details summary:hover{color:var(--jade-deep)}
.entry details[open] summary{margin-bottom:6px}
.entry p{font-size:14.5px;line-height:2;color:var(--body)}
.entry p+p{margin-top:6px}
.entry code{font-family:var(--sans);font-size:12.5px;background:var(--jade-soft);color:var(--jade-deep);padding:1px 7px;border-radius:5px;word-break:break-word}
.quotes{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.quote{background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:28px 28px 22px;position:relative}
.quote::before{content:"“";position:absolute;top:4px;left:16px;font-family:var(--serif);font-size:60px;color:var(--cinnabar);opacity:.28;line-height:1}
.q-txt{font-family:var(--serif);font-size:15.5px;color:var(--ink);font-weight:600;line-height:1.95;text-wrap:balance}
.q-who{margin-top:12px;font-family:var(--sans);font-size:12px;color:var(--muted);letter-spacing:.12em}
.faces{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}
.face{background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:22px 24px;transition:border-color .3s cubic-bezier(.25,1,.5,1),transform .3s cubic-bezier(.25,1,.5,1),box-shadow .3s cubic-bezier(.25,1,.5,1)}
.face:hover{border-color:#CDBF9F;box-shadow:0 12px 30px rgba(120,104,70,.08);transform:translateY(-2px)}
.face .v{font-family:var(--serif);font-size:15px;color:var(--ink);font-weight:600;line-height:1.95}
.face .who{margin-top:10px;font-family:var(--sans);font-size:12px;color:var(--muted);display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.face .who b{color:var(--jade-deep);font-size:13.5px;font-weight:700}
.face .who .tag{color:var(--cinnabar);border:1px solid #D9B9AC;background:var(--cinnabar-soft);padding:0 8px;border-radius:99px;font-size:11px}
.face .who .cnt{margin-left:auto;letter-spacing:.06em}
.faces-note{margin-top:12px;font-family:var(--sans);font-size:12px;color:var(--muted)}
.caps{max-width:860px}
.cap-row{display:flex;flex-direction:column;gap:0;max-width:860px}
.gal-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;max-width:1000px}
.gal{margin:0}
.gal img{width:100%;height:150px;object-fit:cover;border-radius:6px;border:1px solid var(--hair);background:var(--paper-2)}
.gal figcaption{font-family:var(--sans);font-size:11px;color:var(--muted);text-align:center;margin-top:4px}
.cap{display:flex;gap:18px;padding:17px 4px;border-bottom:1px solid var(--hair-2);align-items:baseline}
.cap:last-child{border-bottom:none}
.cap .lbl{flex:none;width:92px;font-family:var(--sans);font-size:12px;color:var(--cinnabar);letter-spacing:.12em;font-weight:700}
.cap .d{flex:none;width:118px;font-family:var(--sans);font-size:12px;color:var(--muted);letter-spacing:.04em}
.cap .t{font-size:14.5px;color:var(--body);line-height:1.95}
.cap .t b{color:var(--ink)}
.epilogue{margin-top:16px;padding:32px 36px;border-radius:10px;color:#F2EDE2;background:linear-gradient(135deg,var(--jade-deep),var(--jade) 70%,#55725F)}
.epilogue h3{font-size:18px;font-weight:700;letter-spacing:.04em}
.epilogue p{margin-top:10px;font-size:14px;line-height:2;color:#DFE7DD}
.epilogue p b{color:#fff}
.f-flash{text-align:center;padding:18px 0 30px;border-bottom:1px solid var(--hair);margin-bottom:34px}
.f-big{font-family:var(--serif);font-size:24px;font-weight:700;color:var(--ink);letter-spacing:.12em;margin-bottom:10px}
.f-big b{color:#A63D24}
.f-small{font-size:12px;color:var(--muted)}
.f-small a{color:var(--muted);text-decoration:underline;text-underline-offset:3px}
.f-small code{background:transparent;padding:0}
footer{margin-top:76px;padding:40px 0 56px;border-top:1px solid var(--hair);font-family:var(--sans);font-size:12px;color:var(--muted);line-height:2.1}
footer .f-title{font-family:var(--serif);font-size:15px;color:var(--ink);font-weight:700;letter-spacing:.1em;margin-bottom:8px}
.reveal{opacity:0;transform:translateY(16px);transition:opacity .7s cubic-bezier(.25,1,.5,1),transform .7s cubic-bezier(.25,1,.5,1)}
.reveal.on{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.reveal{opacity:1;transform:none;transition:none}*{transition:none!important}}
@media (max-width:860px){.hero{padding-top:56px}.stats{grid-template-columns:1fr 1fr}.stats .cell{border-bottom:1px solid var(--hair-2)}
.stats .cell:nth-last-child(-n+2){border-bottom:none}.quotes{grid-template-columns:1fr}.wrap{padding:0 20px}.ch-index .cn{font-size:42px}.toc{margin-left:-20px;margin-right:-20px}.toc-inner{padding:11px 20px}.toc a{padding:8px 6px}.faces{grid-template-columns:1fr 1fr}}
@media (max-width:560px){.seal{width:64px;height:64px;font-size:24px}.hero-row{display:block;position:relative}.hero .seal{position:absolute;top:-6px;right:0;margin-top:0}.hero h1{padding-right:78px}.kicker{font-size:11px;letter-spacing:.18em}.kicker span{white-space:nowrap}.stats .num{font-size:24px}.entry{padding:20px 18px}.faces{grid-template-columns:1fr}.cap{flex-wrap:wrap;gap:6px 14px}.cap .lbl,.cap .d{width:auto}.table-wrap table{min-width:0}thead th{white-space:normal;letter-spacing:.08em}th,td{padding:9px 10px;font-size:12px;line-height:1.6}}
"""

JS = """
(function(){
  "use strict";
  var reveals=document.querySelectorAll(".reveal");
  if("IntersectionObserver" in window){
    var io=new IntersectionObserver(function(es){
      es.forEach(function(en){if(en.isIntersecting){en.target.classList.add("on");io.unobserve(en.target);}});
    },{threshold:0.08,rootMargin:"0px 0px -40px 0px"});
    reveals.forEach(function(el){io.observe(el);});
  }else{reveals.forEach(function(el){el.classList.add("on");});}
  var links=[].slice.call(document.querySelectorAll("#toc a"));
  var secs=links.map(function(a){return document.querySelector(a.getAttribute("href"));});
  function onScroll(){
    var y=window.scrollY,cur=0;
    for(var i=0;i<secs.length;i++){if(secs[i]&&secs[i].offsetTop<=y+window.innerHeight*0.4){cur=i;}}
    links.forEach(function(a,i){a.classList.toggle("active",i===cur);});
  }
  window.addEventListener("scroll",onScroll,{passive:true});onScroll();
})();
/* 话题地图：d3-force 力导向 + 拖拽（成熟组件，勿手搓物理） */
(function(){
  var dEl=document.getElementById("graph-data"),svg=document.getElementById("topic-graph");
  if(!dEl||!svg||!window.d3||!d3.forceSimulation)return;
  var D;try{D=JSON.parse(dEl.textContent);}catch(e){return;}
  var W=D.W,H=D.H;
  var N=D.nodes.map(function(n){return {id:n.id,x:n.x,y:n.y,r:n.r};});
  var ix={};N.forEach(function(n,i){ix[n.id]=i;});
  var E=[];D.edges.forEach(function(e){
    if(ix[e.a]!==undefined&&ix[e.b]!==undefined)E.push({source:e.a,target:e.b});});
  var adj=N.map(function(){return [];});
  E.forEach(function(e){adj[ix[e.source]].push(ix[e.target]);adj[ix[e.target]].push(ix[e.source]);});
  var gE=[].slice.call(svg.querySelectorAll(".gedge"));
  var gN=[].slice.call(svg.querySelectorAll(".gnode"));
  if(gN.length!==N.length)return;
  var gC=gN.map(function(g){return g.querySelector("circle");});
  var gT=gN.map(function(g){return g.querySelector("text");});
  function draw(){
    E.forEach(function(e,k){var l=gE[k];if(!l)return;
      l.setAttribute("x1",e.source.x.toFixed(1));l.setAttribute("y1",e.source.y.toFixed(1));
      l.setAttribute("x2",e.target.x.toFixed(1));l.setAttribute("y2",e.target.y.toFixed(1));});
    N.forEach(function(n,i){
      gC[i].setAttribute("cx",n.x.toFixed(1));gC[i].setAttribute("cy",n.y.toFixed(1));
      gT[i].setAttribute("x",n.x.toFixed(1));gT[i].setAttribute("y",(n.y+n.r+15).toFixed(1));});
  }
  var sim=d3.forceSimulation(N)
    .force("link",d3.forceLink(E).id(function(d){return d.id;}).distance(165).strength(0.6))
    .force("charge",d3.forceManyBody().strength(-1500))
    .force("x",d3.forceX(W/2).strength(0.08))
    .force("y",d3.forceY(H/2).strength(0.09))
    .force("collide",d3.forceCollide(function(d){return d.r+14;}).iterations(2))
    .alpha(0.8).on("tick",function(){
      // d3 官方推荐: tick 内 clamp 约束到画布
      N.forEach(function(n){
        n.x=Math.max(n.r+24,Math.min(W-n.r-24,n.x));
        n.y=Math.max(n.r+16,Math.min(H-n.r-22,n.y));
      });
      draw();
    });
  function toSvg(ev){
    var mt=svg.getScreenCTM();if(!mt)return null;
    var m=mt.inverse();
    if(typeof DOMPoint!=="undefined"){
      try{return new DOMPoint(ev.clientX,ev.clientY).matrixTransform(m);}catch(e){}
    }
    var p=svg.createSVGPoint();p.x=ev.clientX;p.y=ev.clientY;return p.matrixTransform(m);
  }
  gN.forEach(function(g,i){
    g.addEventListener("pointerdown",function(ev){
      ev.preventDefault();
      try{g.setPointerCapture(ev.pointerId);}catch(e){}
      var n=N[i];n.fx=n.x;n.fy=n.y;
      sim.alphaTarget(0.3).restart();
      var ttl=g.querySelector("title");if(ttl)ttl.parentNode.removeChild(ttl);
      function mv(e){var p=toSvg(e);if(!p)return;
        n.fx=p.x;n.fy=p.y;draw();}
      function up(){n.fx=null;n.fy=null;sim.alphaTarget(0);if(ttl)g.insertBefore(ttl,g.firstChild);
        g.removeEventListener("pointermove",mv);
        g.removeEventListener("pointerup",up);
        g.removeEventListener("pointercancel",up);}
      g.addEventListener("pointermove",mv);
      g.addEventListener("pointerup",up);
      g.addEventListener("pointercancel",up);
    });
    g.addEventListener("mouseenter",function(){
      svg.classList.add("focusing");g.classList.add("on");
      adj[i].forEach(function(j){gN[j].classList.add("on");});
      E.forEach(function(e,k){if(e.a===i||e.b===i)gE[k].classList.add("on");});
    });
    g.addEventListener("mouseleave",function(){
      svg.classList.remove("focusing");
      gN.forEach(function(x){x.classList.remove("on");});
      gE.forEach(function(x){x.classList.remove("on");});
    });
  });
  var reduce=window.matchMedia&&window.matchMedia("(prefers-reduced-motion:reduce)").matches;
  if(reduce)sim.stop();
})();
"""

def media_section(st, cnum_str):
    """Roadmap 1.3-1.5：媒体三版块（群文件柜/表情图鉴/视频时刻）。
    数据来自 stats.db media 表；无数据自动整体跳过。"""
    media = st.get("media") or []
    if not media:
        return ""
    from collections import Counter
    nick = st["nick"]
    # ---- 群文件柜 ----
    files = [m for m in media if m["media_type"] == "file"]
    file_html = ""
    if files:
        by_ext = Counter((m["file_name"] or "?").rsplit(".", 1)[-1].lower() for m in files if m["file_name"])
        top_files = sorted(files, key=lambda m: -(m["file_size"] or 0))[:12]
        rows = "".join(
            f'<tr><td>{esc(m["file_name"] or "?")[:46]}</td>'
            f'<td>{(m["file_size"] or 0) / 1048576:.1f} MB</td>'
            f'<td>{esc(_t.strftime("%Y-%m-%d", _t.localtime(m["ts"])))}</td></tr>'
            for m in top_files)
        ext_str = " · ".join(f"{e}×{c}" for e, c in by_ext.most_common(6))
        file_html = (f'<div class="table-card reveal"><div class="tc-head">群文件柜 · {len(files)} 份</div>'
                     f'<p class="cc-sub" style="margin:0 0 8px">{esc(ext_str)}</p>'
                     f'<div class="table-wrap"><table><tr><th>文件</th><th>大小</th><th>日期</th></tr>{rows}</table></div>'
                     f'<p class="faces-note">文件以明文存于本机 msg/file/，可直接按名取用</p></div>')
    # ---- 表情图鉴 ----
    emojis = [m for m in media if m["media_type"] == "emoji"]
    emoji_html = ""
    if emojis:
        by_sender = Counter(m["sender"] for m in emojis)
        top_e = "".join(
            f'<tr><td>{i}</td><td>{esc(nick.get(s, s) or "?")}</td><td>{c}</td>'
            f'<td>{c * 100 // max(len(emojis), 1)}%</td></tr>'
            for i, (s, c) in enumerate(by_sender.most_common(8), 1))
        emoji_html = (f'<div class="table-card reveal"><div class="tc-head">表情图鉴 · {len(emojis)} 个</div>'
                      f'<div class="table-wrap"><table><tr><th>#</th><th>谁在发</th><th>个数</th><th>占比</th></tr>{top_e}</table></div>'
                      f'<p class="faces-note">自嘲与互怼的表情是这个群的情绪货币</p></div>')
    # ---- 视频时刻 ----
    vids = [m for m in media if m["media_type"] == "video"]
    vid_html = ""
    if vids:
        total_s = sum((m["duration_ms"] or 0) for m in vids) / 1000
        longest = max(vids, key=lambda m: (m["duration_ms"] or 0))
        vid_html = (f'<div class="cap-row reveal">'
                    f'<div class="cap"><span class="lbl">视频总量</span><span class="t">{len(vids)} 条 · 合计 {total_s/60:.0f} 分钟</span></div>'
                    f'<div class="cap"><span class="lbl">最长一条</span><span class="t">{(longest["duration_ms"] or 0)/1000:.0f} 秒 · '
                    f'{esc(nick.get(longest["sender"], longest["sender"] or "?"))} · '
                    f'{esc(_t.strftime("%Y-%m-%d", _t.localtime(longest["ts"])))}</span></div>'
                    f'</div>')
    if not (file_html or emoji_html or vid_html):
        return ""
    body = file_html + emoji_html + vid_html
    return (f'<section class="ch" id="media"><div class="ch-head reveal">'
            f'<div class="ch-index"><span class="cn">{cnum_str}</span><span class="meta">Media · Files & Moments</span></div>'
            f'<h2>群媒体志</h2><p class="lead">聊天之外的信物：发过的文件、刷屏的表情、拍下的瞬间——图片内容解析见 Roadmap 第二步。</p>'
            f'<div class="rule"></div></div>{body}</section>')


def gallery_section(digest, cnum_str):
    """Roadmap 2.3：图集附录——digest.gallery = {"dir":..., "count":N}，图片 base64 内嵌保持单文件。
    由 decode_image.py batch 先解密出图，AI 挑选后填目录；缺省自动跳过。"""
    g = digest.get("gallery") or {}
    d = g.get("dir")
    if not d or not os.path.isdir(d):
        return ""
    import base64, glob as _g
    files = []
    for pat in ("*.jpg", "*.png", "*.gif"):
        files += _g.glob(os.path.join(d, pat))
    files = sorted(files)[: g.get("count", 12)]
    if not files:
        return ""
    tiles = ""
    total = 0
    for f in files:
        b = open(f, "rb").read()
        # 完整性门禁：只内嵌浏览器可渲染的完整图（防破图，实测教训：wxgf/截断文件会渲染失败）
        mime = None
        if b[:3] == b"\xff\xd8\xff" and b[-2:] == b"\xff\xd9": mime = "jpeg"
        elif b[:4] == b"\x89PNG" and b[-2:] == b"\x60\x82": mime = "png"
        elif b[:4] == b"GIF8" and b[-1:] == b";": mime = "gif"
        if not mime:
            continue
        total += len(b)
        tiles += f'<figure class="gal"><img src="data:image/{mime};base64,{base64.b64encode(b).decode()}" loading="lazy"><figcaption>{esc(os.path.basename(f)[8:16])}</figcaption></figure>'
    return (f'<section class="ch" id="gallery"><div class="ch-head reveal">'
            f'<div class="ch-index"><span class="cn">{cnum_str}</span><span class="meta">Gallery · Moments</span></div>'
            f'<h2>群像图集</h2><p class="lead">{esc(g.get("caption") or "从聊天里打捞的画面，按月抽样解密自本机图片库。")}'
            f'（{len(files)} 张 · {total//1024} KB）</p>'
            f'<div class="rule"></div></div><div class="gal-grid">{tiles}</div></section>')


def build(st, digest):
    g = st["g"]
    mx_day = max(st["daily"], key=lambda k: st["daily"][k])
    # 隐私匿名（digest.rename）：真名/昵称 -> 代号，作用于页面所有名字出口
    # （发言榜、群像判词卡、语录署名、正文提及）。键 = 库内昵称原文（可只写真名部分，
    # 做子串匹配，覆盖"真名-后缀"类群名片）；值 = 页面展示代号。
    # 页面会在 footer 注明已匿名处理。未配置时零影响（老 digest 照常渲染）。
    rename_map = digest.get("rename") or {}

    def anon(nm):
        if not rename_map or not nm:
            return nm
        for k, v in rename_map.items():
            if k and k in nm:
                return v
        return nm

    # 发言榜：digest.exclude 里的账号（官方客服/机器人等）不计入
    excl = set(digest.get("exclude") or [])
    # 审计 D6：统计「实际被剔除掉的数量」而不是 exclude 里配了几个——
    # 昵称写不全/拼错时 len(excl) 会虚报，页面会声称剔除了根本没命中的账号。
    n_excl_hit = sum(1 for nm, _c in st["top_pool"] if (st["nick"].get(nm) or nm) in excl)
    rank = [(nm, c) for nm, c in st["top_pool"] if (st["nick"].get(nm) or nm) not in excl][:10]
    n_renamed = sum(1 for nm, _c in rank if anon(st["nick"].get(nm) or nm) != (st["nick"].get(nm) or nm))
    mx = rank[0][1] if rank else 1
    top_rows = "".join(
        f'<tr><td>{i}</td><td>{esc(anon(st["nick"].get(nm) or nm))}</td><td><span class="bar{" top" if i==1 else ""}" style="width:{c/mx*180:.0f}px"></span>{c} <span class="pct">({c*100/st["total"]:.0f}%)</span></td></tr>'
        for i, (nm, c) in enumerate(rank, 1))
    graph = digest.get("graph") or {}
    graph_html = graph_svg(graph) if graph.get("nodes") and graph.get("edges") else ""
    vendor_js = ""
    if graph_html:
        vp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "d3-force.min.js")
        if os.path.exists(vp):
            with open(vp, encoding="utf-8") as vf:
                vendor_js = f"<script>{vf.read()}</script>"
        else:
            print("提示: 缺少 vendor/d3-force.min.js, 话题地图将不可拖拽")
    graph_section = (f'<section class="ch" id="graph"><div class="ch-head reveal">'
                     f'<div class="ch-index"><span class="cn">络</span><span class="meta">Prologue · Topic Graph</span></div>'
                     f'<h2>话题地图</h2><p class="lead">把半年的讨论压成一张网：<b>节点</b>是反复出现的关键词（越大越热），'
                     f'<b>连线</b>是它们在同一批对话里的纠缠——像一张 wiki 双链图。</p><div class="rule"></div></div>'
                     f'<div class="graph-card reveal">{graph_html}</div></section>') if graph_html else ""
    d0s, d1s = st["d0"].replace("-", "."), st["d1"].replace("-", ".")
    themes = digest.get("themes", [])
    n_th = len(themes)
    def cnum(k):
        c = "壹贰叁肆伍陆柒捌玖拾"
        return c[k - 1] if 1 <= k <= len(c) else str(k)
    def _apply_rename_th(th, fn):
        """对 theme 的导语/条目标题/正文/表格做真名→代号替换（受控 HTML，子串替换安全）"""
        th = dict(th)
        if th.get("lead"): th["lead"] = fn(th["lead"])
        if th.get("table"):
            t = dict(th["table"])
            t["rows"] = [[fn(c) if isinstance(c, str) else c for c in row] for row in t.get("rows", [])]
            th["table"] = t
        if th.get("items"):
            th["items"] = [{**it, "title": fn(it.get("title") or ""),
                            "body_html": fn(it.get("body_html") or "")} for it in th["items"]]
        return th

    quotes_html = quote_cards(digest.get("quotes", []))
    # 语录署名走匿名（rename 已在 build 顶部定义）
    if rename_map:
        quotes_html = "".join(
            f'<div class="quote reveal"><div class="q-txt">{esc(q["text"])}</div>'
            f'<div class="q-who">{esc(anon(q["who"]))} · {esc(q["date"])}</div></div>'
            for q in digest.get("quotes", []))
    epilogue_html = digest.get("epilogue_html", "")
    faces = digest.get("personas") or []
    # 正文/判词里的真名也统一替换（body_html 与 verdict 是受控 HTML，直接子串替换）
    if rename_map:
        def _apply_rename(s):
            if not s: return s
            for k, v in rename_map.items():
                if k: s = s.replace(k, v)
            return s
        epilogue_html = _apply_rename(epilogue_html)
        themes = [_apply_rename_th(t, _apply_rename) for t in themes]
        faces = [{**p, "nick": anon(p["nick"]), "verdict": _apply_rename(p.get("verdict") or "")} for p in faces]
    # 渲染必须在替换之后（此前渲染先行导致 body_html 真名漏网——实测抓出）
    themes_html = "".join(theme_section(th, cnum(i + 2)) for i, th in enumerate(themes))
    faces_html = "".join(
        f'<div class="face reveal"><div class="v">{esc(p["verdict"])}</div>'
        f'<div class="who"><b>{esc(p["nick"])}</b>'
        + (f'<span class="tag">{esc(p["tag"])}</span>' if p.get("tag") else "")
        + (f'<span class="cnt">{esc(str(p["msgs"]))} 条</span>' if p.get("msgs") else "")
        + "</div></div>" for p in faces)
    faces_block = (f'<div class="faces">{faces_html}</div>'
                   + (f'<p class="faces-note">{esc(_apply_rename(digest["personas_note"]) if rename_map else digest["personas_note"])}</p>' if digest.get("personas_note") else "")
                   ) if faces_html else ""
    caps = digest.get("capsules") or []
    if rename_map:
        def _cap(c):
            c = dict(c)
            if c.get("text"): c["text"] = _apply_rename(c["text"])
            if c.get("text_html"): c["text_html"] = _apply_rename(c["text_html"])
            if c.get("who"): c["who"] = anon(c["who"])
            return c
        caps = [_cap(c) for c in caps]
    caps_html = "".join(
        f'<div class="cap reveal"><span class="lbl">{esc(c["label"])}</span>'
        f'<span class="d">{esc(c.get("date",""))}</span>'
        f'<span class="t">{c["text_html"] if "text_html" in c else esc(c["text"])}</span></div>' for c in caps)
    cno_caps = n_th + 2
    media_sec = media_section(st, cnum(n_th + 2))
    if media_sec:                          # 媒体版块插在主题章与胶囊之间，序号顺延
        cno_caps = n_th + 3
    gallery_sec = gallery_section(digest, cnum(cno_caps)) if media_sec else gallery_section(digest, cnum(n_th + 2))
    if gallery_sec:
        cno_caps += 1
    cno_quotes = cno_caps + 1 if caps_html else cno_caps
    caps_section = (f'<section class="ch" id="capsules"><div class="ch-head reveal">'
                    f'<div class="ch-index"><span class="cn">{cnum(cno_caps)}</span><span class="meta">Interlude · Time Capsules</span></div>'
                    f'<h2>时间胶囊</h2><p class="lead">第一次与最后一次，疯狂与深夜——把值得记住的时刻封进胶囊。</p>'
                    f'<div class="rule"></div></div><div class="caps">{caps_html}</div></section>') if caps_html else ""
    lede = (f'{st["span_days"]} 天，{st["total"]:,} 条对话，{st["speakers"]} 位发言者。'
            f'这不是聊天记录，而是一本<b>编辑部手册</b>：全部消息经通读、提炼、重组，'
            f'只留下<em>值得重读的知识与共识</em>。数据同源统计底座，发信人经双重校验。')
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(g["name"])} · 微信拾光</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="hero">
  <div class="kicker"><span><b>微信拾光</b> · 精选</span><span>{d0s} — {d1s}</span></div>
  <div class="hero-row"><div class="hero-title">
    <h1>{esc(g["name"])}<span class="en">A Community Digest · Vol.01</span></h1></div>
    <div class="seal">拾光<small>留影</small></div></div>
  <p class="lede">{lede}</p>
  <div class="stats">
    <div class="cell"><div class="num">{st["span_days"]}<i>天</i></div><div class="lbl">时间跨度</div></div>
    <div class="cell"><div class="num">{st["total"]:,}<i>条</i></div><div class="lbl">有效消息</div></div>
    <div class="cell"><div class="num">{st["speakers"]}<i>位</i></div><div class="lbl">发言群友</div></div>
    <div class="cell hot"><div class="num">{len(st["longs"])}<i>篇</i></div><div class="lbl">百字长文</div></div>
  </div>
  <div class="chart-card"><div class="cc-head"><span class="cc-title">每日消息量</span>
    <span class="cc-sub">峰值 {mx_day}（{st["daily"][mx_day]} 条）· {len(st["daily"])} 个活跃日</span></div>
    {svg_bars(st["daily"])}</div>
</header>

<nav class="toc" id="toc"><div class="toc-inner">
  <a href="#graph">话题地图</a><a href="#voices">壹 · 群像</a>{''.join(f'<a href="#{th["id"]}">{cnum(i + 2)} · {th["title"]}</a>' for i, th in enumerate(digest.get("themes", [])))}{(f'<a href="#media">{cnum(n_th + 2)} · 群媒体志</a>' if media_sec else '')}{(f'<a href="#gallery">群像图集</a>' if gallery_sec else '')}{(f'<a href="#capsules">{cnum(cno_caps)} · 时间胶囊</a>' if caps_section else '')}<a href="#quotes">{cnum(cno_quotes)} · 语录</a></div></nav>

{graph_section}

<section class="ch" id="voices">
  <div class="ch-head reveal"><div class="ch-index"><span class="cn">壹</span><span class="meta">Chapter 00 · Voices</span></div>
  <h2>群像：谁在撑起这个群</h2>
  <p class="lead">Top 10 贡献了全部消息的 <b>{sum(c for _, c in rank) * 100 // st["total"]}%</b>——少数人维持温度，多数人偶尔冒泡。{('（已剔除 %d 个官方/机器人账号）' % n_excl_hit) if n_excl_hit else ''}{('（已对 %d 位群友做代号匿名处理）' % n_renamed) if n_renamed else ''}</p><div class="rule"></div></div>
  <div class="table-card reveal"><div class="tc-head">发言榜</div><div class="table-wrap"><table>
    <thead><tr><th>#</th><th>群友</th><th>消息量 / 占比</th></tr></thead><tbody>{top_rows}</tbody>
  </table></div></div>
  {faces_block}
</section>

{themes_html}

{media_sec}

{gallery_sec}

{caps_section}

<section class="ch" id="quotes">
  <div class="ch-head reveal"><div class="ch-index"><span class="cn">{cnum(cno_quotes)}</span><span class="meta">Chapter · Quotes</span></div>
  <h2>群友语录</h2>
  <p class="lead">通读全部消息后留下的声音。</p><div class="rule"></div></div>
  <div class="quotes">{quotes_html}</div>
  <div class="epilogue reveal"><h3>尾声</h3>{epilogue_html}</div>
</section>

<footer>
<div class="f-flash"><div class="f-big">你是群里最<b>靓</b>的仔！</div><p class="f-small">Wechat-Memoir 微信拾光 skill 下载地址：<a href="https://github.com/izetaiota/Wechat-Memoir">https://github.com/izetaiota/Wechat-Memoir</a></p></div>
<div class="f-title">关于本页</div>
<p>数据源 wechat_stats.db（发信人身份经前缀+名册双重校验）；主题手册由 AI 通读 {st["total"]:,} 条消息后提炼（{esc(digest.get("editor",""))}，版本 {esc(digest.get("digest_version",""))}）。引语均出自聊天原文。生成：{esc(_t.strftime("%Y-%m-%d %H:%M"))}。</p></footer>
</div>{vendor_js}<script>{JS}</script></body></html>"""

def validate_digest(d):
    """审计 D4：digest.json 由 AI/人工手写，缺必填字段时原来只报裸 KeyError（没有字段路径，极难定位）。
    这里做最小 schema 校验，把缺失定位到具体字段路径。可选字段缺省仍照旧自动跳过。"""
    if not isinstance(d, dict):
        sys.exit("[x] digest.json 顶层必须是 JSON 对象")
    errs = []
    def miss(o, k, path):
        if not isinstance(o, dict) or k not in o:
            errs.append(f"{path}.{k} 缺失")
    for i, th in enumerate(d.get("themes") or []):
        p = f"themes[{i}]"
        for k in ("id", "title", "items"):
            miss(th, k, p)
        if not isinstance(th.get("items"), list):
            errs.append(f"{p}.items 必须是数组")
        else:
            for j, it in enumerate(th["items"]):
                for k in ("no", "title", "body_html"):
                    miss(it, k, f"{p}.items[{j}]")
        tb = th.get("table")
        if isinstance(tb, dict) and tb.get("rows") and "cols" not in tb:
            errs.append(f"{p}.table.cols 缺失（有 rows 就必须配 cols）")
    for i, q in enumerate(d.get("quotes") or []):
        for k in ("text", "who", "date"):
            miss(q, k, f"quotes[{i}]")
    for i, pz in enumerate(d.get("personas") or []):
        for k in ("verdict", "nick"):
            miss(pz, k, f"personas[{i}]")
    for i, c in enumerate(d.get("capsules") or []):
        if not isinstance(c, dict) or ("text" not in c and "text_html" not in c):
            errs.append(f"capsules[{i}] 需有 text 或 text_html")
    g = d.get("graph")
    if isinstance(g, dict) and (g.get("nodes") or g.get("edges")):
        for i, n in enumerate(g.get("nodes") or []):
            miss(n, "id", f"graph.nodes[{i}]")
        for i, e in enumerate(g.get("edges") or []):
            for k in ("a", "b"):
                miss(e, k, f"graph.edges[{i}]")
    if errs:
        sys.exit("[x] digest.json 字段校验未通过（共 %d 处）:\n  - " % len(errs) + "\n  - ".join(errs))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, help="群名片段(需唯一命中)")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="wechat_stats.db 路径（必填；由 Wechat-Memoir 第一阶段（wx_export.py --sqlite）产出）")
    ap.add_argument("--out", default=None, help="输出 HTML, 默认 <db目录>/outputs/rendered/<群名>_群刊.html")
    ap.add_argument("--workdir", default=None, help="insights 目录, 默认 <db目录>/.workbuddy/insights")
    a = ap.parse_args()
    if not a.db:
        sys.exit("[x] 未指定数据库：请用 --db 指向 wechat_stats.db。\n"
                 "    该库由 Wechat-Memoir 第一阶段产出：wx_export.py --group 群名 --sqlite wechat_stats.db")
    if not os.path.isfile(a.db):
        sys.exit(f"[x] 找不到数据库文件: {a.db}\n"
                 "    请先用 wx_export.py --sqlite 生成该库，或检查 --db 路径是否正确。")
    # 审计 D9：--db 是相对路径时 dirname 为空串，产物会落到 CWD 而不是库目录
    db_dir = os.path.dirname(os.path.abspath(a.db))
    workdir = a.workdir or os.path.join(db_dir, ".workbuddy", "insights")
    conn = sqlite3.connect(a.db); conn.row_factory = sqlite3.Row
    room, name = fetch_room(conn, a.group)
    g, msgs, nick, media = load(conn, room)
    st = compute(g, msgs, nick)
    st["media"] = media
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")
    digest_path = os.path.join(workdir, f"{safe}_digest.json")
    if not os.path.exists(digest_path):
        sys.exit(f"缺少编辑部稿 {digest_path}——铁律: 页面必须经 AI 提炼。"
                 f"先用 export_digest_src.py 切片, AI 通读后写 digest.json")
    try:
        with open(digest_path, encoding="utf-8") as f:
            digest = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"[x] 编辑部稿不是合法 JSON: {digest_path}\n    {e}")
    validate_digest(digest)   # 审计 D4：缺必填字段时给带路径的报错，而不是裸 KeyError
    doc = build(st, digest)
    out = a.out or os.path.join(db_dir, "outputs", "rendered", f"{safe}_群刊.html")
    # 审计 D1：新机器/自定义 --out 的目录不存在时会 FileNotFoundError，先建目录
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"OK {out} ({os.path.getsize(out)/1024:.0f} KB, 长文 {len(st['longs'])} 篇, "
          f"图节点 {len((digest.get('graph') or {}).get('nodes', []))} 个)")

if __name__ == "__main__":
    main()
