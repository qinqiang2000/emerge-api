# 2026-08-10 — Agent parity with `claude code + ssh`

## 起因

Dogfood（prod，`海信日本-627人工标注` / `receipt(小票)_海信日本`）连续两次翻车：

- **图 4**：用户要「导出发票+GT 打成 zip」。agent 用 Bash 造出了 zip，但只能交付服务器绝对路径
  `/root/emerge/backend/workspace/teams/.../_export/xxx.zip`。用户在 web 上，等于没交付。
- **图 5**：用户要「打包 docs 并给可下载链接」。agent 去逆向工程自己的后端找下载通道
  （`grep attachments` → 读 `docs.py` → 读 `upload.py`），撞上 `max_turns=20`，
  整轮标成 `error_max_turns after 21 turns` 丢弃。

用户的判断：用 claude code CLI + ssh 干同样的事是确定的，为什么 emerge 里不是。

## 诊断：三个独立缺口，不是一个

`ssh` 之所以确定，靠三件东西，emerge 只有第一件：

| ssh 的能力 | emerge 现状 |
|---|---|
| 任意动作（bash 图灵完备） | ✅ 已有（SDK Bash + 三层权限栈） |
| 回传通道（`scp` / stdout） | ❌ **缺** → 图 4 |
| 不失忆（失败可续、认知留存） | ❌ **缺** → 图 5 |

第三件其实是两层：**单轮内**撞上限不该报废（软着陆），**跨轮/跨会话**探索成果不该蒸发（memory）。

### 缺口 A — 出站数据平面缺失

emerge 的**上行**数据平面是完整的：`tools/upload_url.py` 铸 HMAC 能力 URL →
`POST /lab/upload/{token}` 收字节（控制面走 MCP，数据面走 HTTP，S3 presigned 模式）。

**下行一个都没有**。全仓唯一的 download 是 `api/routes/export.py:34`
`/lab/projects/{slug}/export`，写死 publish bundle（versions + README + curl 脚手架），
与"任意文件"无关。skill prompts 里关于导出/下载的指导：0 行。

### 缺口 B — 回合破产

`chat/service.py:800` `max_turns=20`；`service.py:1376-1391` 把 SDK 的
`ResultMessage.subtype` 原样透传成 error。含义：agent 干了 20 轮活，只要没在第 20 轮
说完话，中间产物 / 已读懂的路由 / 已算出的结论**全部标成 error 丢弃**。

ssh 里没有这个东西。这是"同事"与"会话超时"的分界线。

### 缺口 C — 无记忆，每次重新推导

emerge 传的是**自定义字符串 system prompt**（`service.py:741` → `_build_system_prompt`），
不是 `claude_code` preset。而 Claude Code 的 auto-memory 是 preset 的**动态段**
（SDK `types.py:47`：`exclude_dynamic_sections` 注释里列出 working directory / auto-memory /
git status 三段）。所以 emerge **一点 memory 都拿不到**。

改用 preset 可以白嫖，但会把整个 Claude Code 编码 agent 人格拖进来 —— 对文档同事是错的，**否决**。
emerge 自建，形状照抄 auto-memory（用户已验证过它有效：本仓库的 CLI 侧 auto-memory 已积累 65 条）。

B 和 C 的关系：B 是所有能力缺口的**放大器**，C 是**根因**。只补 A，下次换个没被教过的
操作照样 21 turns 报废。

## T1 — SDK 升级（前置）

`0.2.105` → `0.2.135`（PyPI 最新，差 30 个版本）。本地 + 远端 prod 都升。

拿到的关键新面：`ResultMessage.terminal_reason`（`"completed"` / `"max_turns"` /
`"aborted_streaming"` / `"aborted_tools"`），比现在判 `subtype` 干净 —— 正好是 T2 的判别器。
旧 CLI 上为 `None`，所以 T2 必须 `terminal_reason` 与 `subtype` 双判。

memory 相关的 SDK 面在两个版本间**没有变化**（`AgentDefinition.memory` 作用域字段、
`ContextUsage.memoryFiles` 统计），确认 C 只能自建。

## T2 — max_turns 软着陆

1. `max_turns` 20 → 40（文档 agent 的批量活儿 20 轮不够）。
2. 撞上限**不再**发 error。改为：同 session `resume`，禁全部工具，`max_turns=1`，
   注入一条交接指令，让 agent 用几行说清 **已完成什么 / 产出落在哪 / 下一步是什么**，
   作为正常 `agent_text` 交付；再发一个 `turn_truncated` 事件让前端提示"回复'继续'接着干"。
3. 判别器：`terminal_reason == "max_turns"` 或 `subtype == "error_max_turns"`（旧 CLI 兜底）。

红线：收尾回合**不得调用任何工具**（否则又是一轮 20）。

## T3 — `offer_download`：出站数据平面

严格镜像 `upload_url.py` 的形状，不发明新概念：

- `tools/download_url.py` — `mint_download_token(workspace, rel_path)`，HMAC 签名 + TTL。
  路径过 `workspace_fs._safe_ws_path` 防穿越。
- `@tool offer_download(path)` → `{url, filename, size_bytes}`；HTTP 双形
  `POST /lab/download-urls`（对称不变量测试强制）。
- `GET /lab/download/{token}` 挂**无鉴权** router —— token 即能力，与上传同理。
  `FileResponse` 流式（别学 `export.py` 的 `iter([blob])` 全内存，51MB 的包不该进 RAM）。
- skill rendering contract：`browser` → markdown 链接（`AgentMessage.tsx:60` 已把链接
  渲染成 `<a target=_blank>`，前端零改动）；`headless` → 绝对路径 + curl。

**安全红线**：open mode 下 `current_ws()` 就是真实根，`_auth/`、`_keys.json`、`.env`
都在可达范围内。铸 token 前显式 deny，否则一句"帮我下载配置文件"就把 secrets 送出去。

泛化面：这不是"打包按钮"，是 agent 产物跨越 server→user 边界的**唯一通道** ——
zip / csv / 报表 / agent 现产的自含 HTML（inline Content-Type 即预览页，
复用 review board、audit board 已有的自含 HTML 先例）。

## T4 — Memory：让探索沉淀

形状照抄 Claude Code auto-memory：

- **位置**：`{project}/_memory/*.md` + `{project}/_memory/MEMORY.md` 索引；
  team 级跨项目经验放 `{team}/_memory/`。`_` 前缀 → `orphans._sweep_dir` 天然豁免
  （`orphans.py:53`），无需新增例外。
- **注入**：`_build_active_context` 追加 memory 索引（只注 `MEMORY.md` 一行一条，
  正文按需 Read）。
- **写入**：agent 用已有的 Write/Edit，不新增 tool（Claude Code 自己也是这么做的）。
  权限栈天然允许（workspace 内路径 range-check 通过）。

**红线 1（五层分离）**：memory 只进 **Agent brain** 的 system prompt，
**绝不**进 extract / labeler / proposer / translator 的上下文。

**红线 2（不要变成 global_notes 的影子）**：
- 「日期格式统一 YYYY-MM-DD」「这类票的税号在右上角」→ 属于抽取规则 → 写 `global_notes` / 字段
  `description`，**不是** memory。
- 「这个客户的交付物要 zip 到 `_export/` 再给链接」「这个项目的 GT 在 `reviewed/`
  不在 `predictions/`」「上次 OCR 空页是限流不是空白」→ 属于**干活方式** → 写 memory。

分流写进 skill，否则 agent 会把抽取规则灌进 memory。

## 验收

- 图 5 场景重放：问「把 docs 打包成 zip 并给下载链接」→ 一次 `offer_download` 调用交付，
  无源码探索。
- 人为把 `max_turns` 压到 3 触发上限 → 用户看到交接文字而非 `error_max_turns`。
- memory 分流：给 agent 一条抽取规则 + 一条流程经验，只有后者进 `_memory/`。
- `pytest` 全绿，含新增对称性用例。
