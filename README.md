# Wechat-Memoir · 微信拾光

微信群回忆录一站式技能：从微信 Windows 4.x 本地加密数据库提取密钥、解密，导出群聊 Markdown 与 SQLite 统计底座，再经 AI 通读提炼，渲染成单文件纸刊风群刊网页。

> **v2.0.0**：由 `wechat-group-export`（采矿队）与 `wechat-group-digest`（编辑部）合并而成。一条命令、一句话，从加密数据库到可分享的群回忆录。

## 全景管线

```
微信进程内存 ──提密钥──▶ 解密 db_storage ──解析──▶ <群>_聊天记录.md（按天分组）
                                        └─结构化─▶ wechat_stats.db（统计底座）
                                                        │
              按月切片 → AI 通读 → 领域挖掘 → digest.json ┘
                                                        ▼
                                     <群>_群刊.html（单文件纸刊风网页）
```

## 特性

**采矿段（原 wechat-group-export）**
- 自动探测微信数据目录（绿色版/安装版都认）；密钥只从进程内存捞（XOR 混淆破解 + HMAC-SHA1/salt 硬校验，不靠猜）
- 全程只读、非管理员可用；缓存复用后导下一个群 ~0.5 秒
- 群名安全消歧（多候选取列表不瞎猜）；`--sqlite` 双出口产出统计底座

**编辑部段（原 wechat-group-digest）**
- 铁律：页面必须经 AI 提炼，拒绝纯自动生成
- 管线：按月切片 → AI 通读 → 群型识别 → 领域定向挖掘 → 编辑部稿 → 纸刊风渲染
- 大群模式：分片 map-reduce 通读；超大群（50 万条级）三层法（统计底座 + 抽样 + 领域挖掘）

## 环境要求

| 需要 | 说明 |
|---|---|
| Windows + 微信 4.x | 实测 4.1.13.63 / 4.1.15.13 |
| Python 3.10+ | Windows 版 |
| zstandard | `python -m pip install zstandard`（解压压缩消息，刚需） |

## 快速开始

### 方式 A：交给 AI（推荐）

把本仓库当作一个技能交给 AI 助手（WorkBuddy / Claude 等支持技能机制的 AI），说一句话：

> 把我的「XX交流群」做成回忆录。

AI 会读取 `SKILL.md` 自动完成全流程，并在读写微信进程内存前先征得你的同意。

### 方式 B：命令行

```bash
# 0. 一次性准备
python -m pip install zstandard

# 1. 导出群聊 + 统计底座（--outdir 必填；缓存默认 ~/.wxcache）
cd scripts
python wx_export.py --group "群名" --outdir "D:/微信群导出" --sqlite "D:/微信群导出/wechat_stats.db"

# 2. 切片 → AI 通读写 digest.json → 渲染（详见 SKILL.md 第二阶段）
python export_digest_src.py --group "群名" --db "D:/微信群导出/wechat_stats.db"
#   … AI 通读提炼，写 insights/<群>_digest.json …
python render_group_page.py --group "群名" --db "D:/微信群导出/wechat_stats.db"

# 辅助
python wx_export.py --list-groups   # 列出全部群名
python wx_export.py --purge         # 清缓存（密钥+解密库，敏感）
```

## 隐私红线（务必读）

- 工具**只读**微信进程内存与本地库，不修改微信任何文件、不采集他人账号
- 缓存（`~/.wxcache`）内含**数据库密钥与明文聊天记录**，属敏感数据：用完可 `--purge` 删除
- 所有数据只在本地处理，不上传任何内容
- 涉及读取进程内存，只在**自己的账号、本人同意**前提下使用

## 目录结构

```
Wechat-Memoir/
├── SKILL.md                     # 技能说明书（两阶段全流程、四层不变量、37 条踩坑）
├── scripts/
│   ├── wx_export.py             # 采矿一键流水线（推荐入口）
│   ├── extract_keys_413.py      # 密钥提取 + XOR 混淆破解
│   ├── export_group_md.py       # 解密库 → 按群导出 Markdown
│   ├── wcdb_key_tool_windows.py # 密钥校验/解密（源自 TANGandXue/wcdb-key-tool，MIT）
│   ├── export_digest_src.py     # 编辑部①：按月切片
│   ├── make_persona_src.py      # 编辑部辅助：Top10 人物单人语料
│   ├── render_group_page.py     # 编辑部④：纸刊风渲染（CSS/JS 单真源）
│   └── vendor/d3-force.min.js   # d3-force v3（有图谱时按需内联）
└── LICENSE
```

## 支持范围与失效处理

微信版本迭代可能使密钥提取失效。失效时按 `SKILL.md` 的「新版本适配判断顺序」逐层排查（症状 → 卡点层级 → 对应踩坑条目）。欢迎提交 issue 附微信版本号与失败日志。

## Roadmap · 媒体处理三步走（2026-10-23 立项）

> 背景：当前管线对图片/表情/视频/文件**仅计数量**（元数据标签），内容未解析。实测本机：90后群 37,625 张图片 + 37,867 个表情 + 4,218 条视频；媒体实体文件都在本机，按下方三步逐步纳入群刊。

### 第一步 · 媒体清单层（零解密，纯元数据）— 状态：已完成 ✅（2026-10-23）

> 预期收益：群刊新增三个版块，1-2 小时可完成

- [x] **1.1 `--media-index` 导出开关**：wx_export.py 解析消息 XML，提取文件名/大小/时长/页面链接，写入 stats.db 新表 `media`（room_id, ts, sender, media_type, file_name, file_size, aeskey/md5, local_path, duration）
  - 文件：type 49 XML 的 `<title>/<totallen>/<fileext>`（本机验证：文件名+大小可提取）
  - 视频：type 43 的 `cdntotaltime`（封面帧 jpg 在 msg/video 下是**明文**可直接引用）
  - 图片：type 3 的 `aeskey`；表情：type 47 的 `md5`
- [x] **1.2 hardlink.db 本地定位桥**：aeskey/md5 → `msg/attach/<md5>/<年月>/Img/xx.dat`、文件 → `msg/file/`（索引表 `file/image/video_hardlink_info_v4`，本机验证可通）
- [x] **1.3 群刊「群文件柜」版块**：按群统计文件清单（Top 类型/大小/时间分布），PDF 等明文文件输出本地相对路径引用——「文件直接用引用到本地」
- [x] **1.4 群刊「表情图鉴」版块**：emoticon.db（已解密，91 个收藏表情的 md5→caption/cdn_url）+ 消息统计「谁最爱发表情」；商店表情 CDN 明文图下载内嵌
- [x] **1.5 群刊「视频时刻」版块**：封面帧（明文 jpg）+ 时长/发送者上下文

### 第二步 · 图片 V2 解密层（攻坚核心）— 状态：待开工 ⬜

> 已完成侦察：V2 格式社区逆向成熟（52pojie/lane2077-wechat-decrypt/upxuu），格式长度公式本机验证 4/4 吻合

- [ ] **2.1 `decode_image.py` 移植**（新脚本，独立于主管线，挂了不影响导出）：
  - 格式：`07 08 56 32 08 07` 魔数 + aes_size(4B LE) + xor_size(4B LE) + 1B pad + AES-128-ECB 段 + **16B 分隔（勿硬编码，按长度跳过）** + XOR 尾段；总长公式 `15 + aes_size + 16 + xor_size`
  - 依赖 `pycryptodome`（AES-ECB；Windows 也可走 bcrypt.dll，参考 wcdb_key_tool 先例）
- [ ] **2.2 密钥提取双路**：
  - 路 A（离线优先）：MMKV 派生——`AppData/Roaming/Tencent/xwechat/net/kvcomm/key_<code>_*.statistic` 文件名 code 参与派生（本机文件已找到，派生算法待逆向确认）
  - 路 B（兜底）：进程内存扫描（微信打开图片时 key 才入内存，find_image_key 模式：取密文前 16B 做验证 oracle）
- [ ] **2.3 群刊「图集附录」版块**：不追求全量解密（51 万张/30GB），只解**群刊选中的代表图**（AI 按消息上下文挑 20-50 张），缩略后 base64 内嵌进单文件 HTML
- [ ] **2.4 回归验证**：抽样解密成功率 ≥95%；解出图与消息时间线对齐抽查

### 第三步 · 内容理解层（多模态增强，可选）— 状态：待开工 ⬜

- [ ] **3.1 图片打标/OCR**：解密后的代表图喂多模态模型（本地或 API），输出「聚餐照/K线截图/风景/合影」标签与图中文字
- [ ] **3.2 打标结果进 AI 通读**：图片内容作为一等公民进切片语料——饭局照片进「活动大事记」、K 线截图进「行情复盘」
- [ ] **3.3 表情包语义**：高频表情的 caption/场景归类，做「群表情文化」小节

### 已验证的技术事实（做的时候直接用，别再踩）

| 事实 | 验证日期 |
|---|---|
| msg/file 普通文件**明文**存储（抽样 400：PDF 191 全明文，pdf 占文件类型 83%） | 2026-10-23 |
| msg/video 封面帧 jpg **明文**；正文 mp4 待验 | 2026-10-23 |
| attach 图片 .dat 全 V2 加密（抽样 300：明文 0 / V2 185 / 已清理 115）；V2 长度公式吻合 | 2026-10-23 |
| hardlink.db 三索引表（文件 3939/图片 36.3 万/视频 2.4 万）；路径链 `attach/<md5>/<年月>/Img/` 可通 | 2026-10-23 |
| emoticon.db 已解密：kNonStoreEmoticonTable 含 md5/caption/cdn_url/aes_key | 2026-10-23 |
| kvcomm/key_*.statistic 文件存在于 AppData（MMKV 密钥派生原料） | 2026-10-23 |
| 视频时长字段是 `playlength`（秒）非 cdntotaltime；`<type>6</type>` 是子元素非属性 | 2026-10-23 |
| 老式 IM 图片附件 appmsg type=8 fileext=pic；两实测群几乎无 type=6 真文件（file=0 是数据事实） | 2026-10-23 |

> 执行原则（沿用 SKILL.md 四层不变量方法论）：解密函数版本无关（V2 结构稳定）独立成脚本；密钥提取层隔离（MMKV 失败自动切内存扫描）；媒体版块全部**可缺省**——不解密也照常出刊，解密只增强不阻塞。

## License

MIT。内嵌第三方组件详见 `LICENSE` 的 Third-party notices（wcdb-key-tool / d3-force）。
