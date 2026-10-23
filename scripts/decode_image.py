#!/usr/bin/env python3
"""decode_image.py — 微信 4.x 图片 .dat 解密（Roadmap 2.1/2.2）

三代格式（本机实测 4.1.15.13，V2 主流）：
  V0 无签名     整文件单字节 XOR（key = 首字节 ^ 0xFF，明文 JPEG 恒 ffd8 开头）
  V1 0708V1..   AES-128-ECB + XOR，社区已破解的固定 key（过渡期产物，偶见）
  V2 0708V2..   AES-128-ECB 头段 + 16B 分隔 + 单字节 XOR 尾段（2025-08+ 主流）
      结构: [6B 魔数][4B aes_size LE][4B xor_size LE][1B flag][AES段][16B分隔][XOR段]
      总长公式: file_size == 15 + aes_size + 16 + xor_size（本机验证吻合）

密钥（Roadmap 2.2 路 A，纯离线派生，无需微信在线）：
  code  = kvcomm/key_<code>_*.statistic 文件名第一个数字
          (%APPDATA%/Tencent/xwechat/net/kvcomm/，另可扫 ilink/kvcomm 与微信数据盘)
  wxid  = 数据目录名清洗掉账号后缀（wxid_xxx_6409 -> wxid_xxx）
  aes_key = md5(f"{code}{wxid}") 的 hexdigest 前 16 个 ASCII 字符直接当 16 字节密钥
            （是 ASCII 字符串本身，不是 hex 解码！）
  xor_key = code & 0xFF
  验证 oracle：解密任一 V2 头段，命中 ffd8/8950 4E47/GIF8/RIFF/wxgf 即正确

路 B（兜底，未实现于本脚本）：进程内存扫描——图片被查看时 key 才入内存，
  适合账号异常场景引导式抓取；正确架构是路 A 为主、路 B 兜底。

wxgf（微信自研图片封装）：解密后头 4 字节为 "wxgf" 时需经 VoipEngine.dll 的
  wxam_dec_wxam2pic_5 转码（微信安装目录自带）；本脚本 --wxgf 开关启用。

用法：
  # 单文件解密（自动探测 code/wxid，密钥缓存 ~/.wxcache/image_key.json）
  python decode_image.py decrypt --dat "path/to/x.dat" --out "out.jpg"

  # 批量：从 stats.db media 表取某群图片 aeskey 定位文件并解密 N 张
  python decode_image.py batch --db wechat_stats.db --group "群名" --out-dir "./imgs" --limit 20

  # 只派生密钥（打印并缓存）
  python decode_image.py key [--code 2793693271] [--wxid wxid_xxx_ee99]
"""
import argparse
import glob
import hashlib
import json
import os
import re
import struct
import sys

V2_MAGIC = b"\x07\x08V2\x08\x07"
V1_MAGIC = b"\x07\x08V1\x08\x07"
IMG_HEADS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"wxgf")
CACHE = os.path.join(os.path.expanduser("~"), ".wxcache", "image_key.json")


def find_code():
    """扫 kvcomm 目录提取 code（多个目录/多个 code 都收集）。"""
    codes = set()
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), "Tencent", "xwechat", "net", "kvcomm"),
        os.path.join(os.environ.get("APPDATA", ""), "Tencent", "xwechat", "net", "ilink", "kvcomm"),
    ]
    # 微信数据盘兜底：常见自定义位置
    for drive in ("C:", "D:", "E:"):
        roots.append(os.path.join(drive + os.sep, "xwechat_files"))
    for root in roots:
        if not os.path.isdir(root):
            continue
        for p in glob.glob(os.path.join(root, "**", "key_*"), recursive=True)[:400]:
            m = re.match(r"key_(\d+)_", os.path.basename(p))
            if m:
                codes.add(int(m.group(1)))
    return sorted(codes)


def clean_wxid(wxid: str) -> str:
    parts = wxid.split("_")
    if wxid.startswith("wxid_") and len(parts) >= 3:
        return "_".join(parts[:2])
    return wxid


def derive_key(code: int, wxid: str):
    """MMKV 离线派生：aes_key = md5(code+清洗wxid) hex 前 16 字符；xor = code & 0xFF。"""
    aes_key = hashlib.md5(f"{code}{clean_wxid(wxid)}".encode()).hexdigest()[:16].encode()
    return aes_key, code & 0xFF


def load_cached_key():
    if os.path.exists(CACHE):
        try:
            j = json.load(open(CACHE, encoding="utf-8"))
            return j.get("aes_key", "").encode(), j.get("xor_key", 0)
        except Exception:
            pass
    return None, None


def save_cached_key(aes_key: bytes, xor_key: int, code: int, wxid: str):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"aes_key": aes_key.decode(), "xor_key": xor_key,
               "code": code, "wxid": wxid, "note": "敏感：图片密钥，勿上传"},
              open(CACHE, "w", encoding="utf-8"))


def decrypt_v2(data: bytes, aes_key: bytes, xor_key: int) -> bytes:
    assert data[:6] == V2_MAGIC, "非 V2"
    aes_size, xor_size = struct.unpack("<II", data[6:14])
    from Crypto.Cipher import AES   # 延迟导入：只有真解密才需要 pycryptodome
    n = aes_size - aes_size % 16    # ECB 要求 16 对齐；个别文件 aes_size 非对齐（截到块边界）
    head = AES.new(aes_key, AES.MODE_ECB).decrypt(data[15:15 + n])[:aes_size]
    tail = bytes(b ^ xor_key for b in data[15 + aes_size + 16:15 + aes_size + 16 + xor_size])
    return head + tail


def decrypt_v0(data: bytes) -> bytes:
    """无签名旧格式：单字节 XOR，key 由明文 JPEG 首字节 0xFF 推导。"""
    key = data[0] ^ 0xFF
    out = bytes(b ^ key for b in data)
    return out if out[:3] in IMG_HEADS else None


def looks_like_image(b: bytes) -> bool:
    return any(b.startswith(h) for h in IMG_HEADS)


def renderable_image(b: bytes):
    """严格校验：只认浏览器可渲染的完整图。返回扩展名（jpg/png/gif）或 None。
    wxgf（微信自研）与截断文件不算——图集宁缺毋滥（破图比缺图伤体验，实测教训）。
    JPEG: 头 ffd8ff + 尾 ffd9；PNG: 头 8950 4e47 + 尾 6082（IEND）；GIF: 头 GIF8 + 尾 3b。"""
    if b[:3] == b"\xff\xd8\xff" and b[-2:] == b"\xff\xd9":
        return ".jpg"
    if b[:4] == b"\x89PNG" and b[-2:] == b"\x60\x82":
        return ".png"
    if b[:4] in (b"GIF8",) and b[-1:] == b";":
        return ".gif"
    return None


def resolve_key(oracle_dat: str = None, code=None, wxid=None, no_cache=False):
    """取可用密钥：缓存 > 显式指定 > 全量派生+oracle 验证。返回 (aes, xor, 来源说明)。"""
    if not no_cache:
        aes, xk = load_cached_key()
        if aes:
            return aes, xk, "缓存"
    codes = [code] if code else find_code()
    if not codes:
        sys.exit("[x] 未找到 kvcomm key_* 文件（code 无法提取）。可 --code 手动指定。")
    # wxid：从微信数据目录名探测（xwechat_files/wxid_*）
    wxids = [wxid] if wxid else []
    if not wxids:
        for drive in ("C:", "D:", "E:"):
            base = os.path.join(drive + os.sep, "xwechat_files")
            if os.path.isdir(base):
                wxids += [n for n in os.listdir(base) if n.startswith("wxid_")]
    # oracle：任一 V2 dat 的头段
    oracle = None
    if oracle_dat and os.path.exists(oracle_dat):
        oracle = open(oracle_dat, "rb").read()
    elif not oracle_dat:
        for cand in glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(oracle_dat or "D:/x/")), "**", "*.dat"),
                recursive=True)[:0]:
            pass  # batch 模式由调用方传 oracle；单文件模式用 --dat 自身
    for c in codes:
        for w in wxids:
            aes, xk = derive_key(c, w)
            if oracle and oracle[:6] == V2_MAGIC:
                from Crypto.Cipher import AES
                ct = oracle[15:31]
                if looks_like_image(AES.new(aes, AES.MODE_ECB).decrypt(ct)):
                    save_cached_key(aes, xk, c, w)
                    return aes, xk, f"code={c} wxid={clean_wxid(w)}（oracle 验证通过）"
            else:
                # 无 oracle 时先缓存，decrypt 阶段若失败会再走全组合
                return aes, xk, f"code={c} wxid={clean_wxid(w)}（未验证）"
    sys.exit("[x] 所有 code×wxid 组合均未通过 oracle 验证")


def convert_wxgf(data: bytes, wechat_dir: str = None) -> bytes:
    """wxgf -> 普通图片：调微信自带 VoipEngine.dll 转码。"""
    import ctypes
    dll = None
    for cand in glob.glob(os.path.join(
            wechat_dir or r"D:\Program Files (x86)\Tencent\Weixin", "*", "VoipEngine.dll")):
        dll = cand  # 取最新版本（glob 排序最后一个）
    if not dll:
        # 从运行中的微信定位
        try:
            import subprocess
            out = subprocess.check_output(
                ["powershell", "-NoProfile",
                 "(Get-Process Weixin | Select -First 1 -ExpandProperty Path)"],
                text=True).strip()
            dll = os.path.join(os.path.dirname(out),
                               *[p for p in os.listdir(os.path.dirname(out))], "VoipEngine.dll")
        except Exception:
            pass
    if not dll or not os.path.exists(dll):
        print(f"  [!] wxgf 图片但未找到 VoipEngine.dll，跳过转码（原始字节输出）")
        return data
    os.add_dll_directory(os.path.dirname(dll))
    voip = ctypes.WinDLL(dll)
    fn = voip.wxam_dec_wxam2pic_5
    fn.argtypes = [ctypes.c_int64, ctypes.c_int, ctypes.c_int64,
                   ctypes.POINTER(ctypes.c_int), ctypes.c_int64]
    fn.restype = ctypes.c_int64
    out_buf = ctypes.create_string_buffer(52 * 1024 * 1024)
    out_sz = ctypes.c_int(len(out_buf))
    in_buf = ctypes.create_string_buffer(data, len(data))
    ret = fn(ctypes.addressof(in_buf), len(data),
             ctypes.addressof(out_buf), ctypes.byref(out_sz), None)
    return out_buf.raw[:out_sz.value] if ret == 0 else data


def decrypt_file(dat_path: str, aes_key: bytes, xor_key: int, wxgf=False) -> bytes:
    data = open(dat_path, "rb").read()
    if data[:6] == V2_MAGIC:
        img = decrypt_v2(data, aes_key, xor_key)
    elif data[:6] == V1_MAGIC:
        print("  [!] V1 过渡格式暂不支持（罕见），跳过")
        return None
    else:
        img = decrypt_v0(data)
        if img is None:
            return None
    if wxgf and img[:4] == b"wxgf":
        img = convert_wxgf(img)
    return img


def cmd_key(args):
    aes, xk, src = resolve_key(code=args.code, wxid=args.wxid, no_cache=args.no_cache)
    print(f"aes_key = {aes.decode()}\nxor_key = {xk:#04x}\n来源: {src}\n缓存: {CACHE}")


def cmd_decrypt(args):
    aes, xk, src = resolve_key(oracle_dat=args.dat, code=args.code, wxid=args.wxid)
    print(f"密钥来源: {src}")
    img = decrypt_file(args.dat, aes, xk, wxgf=args.wxgf)
    if img is None:
        sys.exit("[x] 解密失败（格式不支持或密钥错误）")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "wb").write(img)
    kind = "JPEG" if img[:3] == b"\xff\xd8\xff" else "PNG" if img[:4] == b"\x89PNG" else img[:4].decode("latin1")
    print(f"[√] {args.out}  {len(img)} 字节  类型 {kind}")


def cmd_batch(args):
    """按月目录批量解密某群图片（消息精确绑定不可行——磁盘文件名与消息 XML 哈希是两套体系，
    实测 packed_info/Bubble 亦不对应；正确策略=按消息月份定位 attach 目录，就近取图）。
    成功率口径（Roadmap 2.4）：抽样显示版图解出合法图片头的比例。"""
    import sqlite3, datetime, random
    con = sqlite3.connect(args.db)
    room = con.execute("SELECT room_id FROM groups WHERE name LIKE ?",
                       (f"%{args.group}%",)).fetchone()
    if not room:
        sys.exit(f"[x] 库中无群「{args.group}」")
    room_id = room[0]
    room_dir = hashlib.md5(room_id.encode()).hexdigest()
    # 该群有图片消息的月份（media 表）
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime('%Y-%m', ts, 'unixepoch', 'localtime') FROM media "
        "WHERE room_id=? AND media_type='image' ORDER BY 1 DESC", (room_id,))]
    aes, xk, src = resolve_key(code=args.code, wxid=args.wxid, no_cache=args.no_cache)
    print(f"密钥来源: {src}\n月份目录: {months}")
    os.makedirs(args.out_dir, exist_ok=True)
    decrypt_ok = total = 0
    picked = 0
    random.seed(7)
    for ym in months:
        if picked >= args.limit:
            break
        d = os.path.join(args.attach_root, room_dir, ym, "Img")
        if not os.path.isdir(d):
            continue
        main_imgs = [f for f in os.listdir(d)
                     if f.endswith(".dat") and not f.rsplit(".", 1)[0].endswith(("_h", "_t"))]
        random.shuffle(main_imgs)
        for fn in main_imgs:
            if picked >= args.limit:
                break
            p = os.path.join(d, fn)
            img = decrypt_file(p, aes, xk, wxgf=args.wxgf)
            total += 1
            ext = renderable_image(img) if img else None
            if ext:
                decrypt_ok += 1
                picked += 1
                out = os.path.join(args.out_dir, f"{ym}_{fn[:-4]}{ext}")
                open(out, "wb").write(img)
    rate = decrypt_ok / total * 100 if total else 0
    print(f"抽样解密 {total} 张，成功 {decrypt_ok}（成功率 {rate:.0f}%）"
          f"{'  ✅ ≥95% 达标（Roadmap 2.4）' if rate >= 95 else '  ⚠️ <95% 待查'}")
    print(f"输出目录: {args.out_dir}（{picked} 张已落盘）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pk = sub.add_parser("key", help="只派生/打印密钥")
    for p in (pk,):
        p.add_argument("--code", type=int)
        p.add_argument("--wxid")
        p.add_argument("--no-cache", action="store_true")
    pd = sub.add_parser("decrypt", help="单文件解密")
    pd.add_argument("--dat", required=True)
    pd.add_argument("--out", required=True)
    pd.add_argument("--wxgf", action="store_true", help="wxgf 自动转码")
    for p in (pd,):
        p.add_argument("--code", type=int)
        p.add_argument("--wxid")
        p.add_argument("--no-cache", action="store_true")
    pb = sub.add_parser("batch", help="按 stats.db media 表批量解密某群图片")
    pb.add_argument("--db", required=True)
    pb.add_argument("--group", required=True)
    pb.add_argument("--out-dir", required=True)
    pb.add_argument("--limit", type=int, default=20)
    pb.add_argument("--attach-root", default=r"D:\xwechat_files\wxid_qw2b2c90yx2o22_ee99\msg\attach",
                    help="msg/attach 根目录")
    pb.add_argument("--wxgf", action="store_true")
    for p in (pb,):
        p.add_argument("--code", type=int)
        p.add_argument("--wxid")
        p.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    {"key": cmd_key, "decrypt": cmd_decrypt, "batch": cmd_batch}[args.cmd](args)


if __name__ == "__main__":
    main()
