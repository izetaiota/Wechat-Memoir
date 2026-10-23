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

## License

MIT。内嵌第三方组件详见 `LICENSE` 的 Third-party notices（wcdb-key-tool / d3-force）。
