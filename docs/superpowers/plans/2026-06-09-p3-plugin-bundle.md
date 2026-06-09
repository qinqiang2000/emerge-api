# 2026-06-09 — P3 plugin bundle（队友一键装 emerge connector）

> **Status**: 📋 planned → implementing
> **Closes**: `2026-06-08-cowork-remote-mcp.md` 的 **P3**。把"贴个人 connector URL"升级为"一键装插件"——队友 `/plugin marketplace add` + `/plugin install` 即得 emerge 远程连接 + `/emerge:*` slash + 自动加载的 agent 引导。tip 2「现在就给客户队友用」的 onboarding 终态。
> **Inputs**: 官方 plugin/marketplace/MCP 文档（已研究）；P0/P1/闭环 dogfood 暴露的远程语境真相。

---

## 研究结论（固化）

Claude plugin = 自包含目录，经 marketplace（git 仓库）分发：

- **`.claude-plugin/plugin.json`**：manifest（仅 `name` 必填；name 即 slash 命名空间 → `/emerge:extract`）。
- **`.mcp.json`**（plugin 根，**不在** `.claude-plugin/` 内）：声明 MCP server。远程用 `{"type":"http","url":"…/mcp/"}`，OAuth DCR 客户端连接时自动触发（我们已 end-to-end 验证）——**无需 headers/手贴 token**。
- **`skills/<name>/SKILL.md`**：model-invoked（Claude 按任务上下文自动加载），YAML frontmatter 带 `description` 触发。
- **`commands/<name>.md`**：显式 `/emerge:<name>` slash，frontmatter `description` + body 指令（`$ARGUMENTS` 取参）。
- **marketplace**：根 `.claude-plugin/marketplace.json` = `{name, owner, plugins:[{name, source, description}]}`；`source` 指 plugin 子目录。队友 `/plugin marketplace add <git-url>` + `/plugin install emerge@emerge`。

## 关键设计决策

1. **SKILL.md 不照搬 server skill（dogfood 实证）**。`emerge_extractor.md`（39KB）是 emerge **自家 agent** 的系统提示：假设 cwd=工作区、每轮注入 `## Active context` 块、有 `ui_*` 浏览器工具。**远程 Cowork 插件用户三者全无**——"Read the Active context block first""use those absolute paths, agent cwd not guaranteed"对它**主动误导**。所以插件 SKILL.md = **手写的 remote-first 薄引导**：orientation + `ws_*` 总线 + 核心动词 cheatsheet + 红线子集 + "深度 playbook 见 connector 暴露的 MCP prompt"。**深度引导单一真相仍在 server**（薄 skill 不复制它，只指向它）→ drift 风险低。
2. **命名 task-agnostic（CLAUDE.md 红线：UI chrome 任务类型无关）**。emerge 是**文档处理能力强的同事**，不是提取专用工具——后续有文档分类、文档匹配等。插件这个**新分发物**一开始就该通用：插件名 `emerge`（非 `emerge-extractor`）→ `/emerge:*`；skill 名 `emerge`，frame 成"文档处理同事：把文档变成 API——当前主力是字段提取，分类/匹配随能力增长"，不写死 invoice/extract 专用词。commands 用通用动词（`run`/`compare`/`tune`/`publish`），不叫 `extract`。server 侧 `emerge-extractor` prompt 名是历史内部命名（重命名是更大重构，本期不动）；插件层先立通用名。
2. **marketplace 寄宿 emerge repo**（`github.com/qinqiang2000/emerge-api`）。marketplace.json 必须在**仓库根** `.claude-plugin/marketplace.json`（`/plugin marketplace add owner/repo` 从根解析它）；plugin 本体落 `plugin/emerge/`，marketplace `source` 用相对路径 `./plugin/emerge`（git-added marketplace 支持相对路径）。私有 repo → 队友需 git 访问（一客户一 team 的现状下可接受）；公开后即开放装。
3. **`.mcp.json` URL 与 prod 同步靠测试守**。URL 硬编码 `https://fpydoc.duckdns.org/mcp/`；加 backend 测试断言它 == `public_base_url + /mcp/`，prod 域名变更时测试红（防 bundle 静默指向旧地址）。
4. **commands 薄、通用动词、指向 MCP 工具**。`/emerge:run|compare|tune|publish` 各一个 md（通用动词，非 `extract`），body 指挥 Claude 用 connector 的 typed 工具跑对应 workflow（server 侧 slash 路由够不到远程客户端，故 plugin 侧自带）。

---

## Bundle 布局

```
<repo-root>/                              # = marketplace 根（emerge-api repo）
├── .claude-plugin/
│   └── marketplace.json                  # 仓库根：列 emerge 插件，source ./plugin/emerge
└── plugin/
    └── emerge/                           # = 插件
        ├── .claude-plugin/
        │   └── plugin.json               # manifest（name=emerge → /emerge:*）
        ├── .mcp.json                     # remote http connector（OAuth 自动）
        ├── skills/
        │   └── emerge/SKILL.md           # 薄 remote-first 引导（model-invoked）
        ├── commands/
        │   ├── run.md / compare.md
        │   └── tune.md / publish.md      # /emerge:* slash（通用动词）
        └── README.md                     # 安装 + 用法
```

## Phases

### P3.0 — bundle + marketplace（本期）

**In:**
- `plugin/emerge/.claude-plugin/plugin.json`：name=emerge、version、description（task-agnostic：文档处理同事）、author、homepage、repository、keywords。
- `plugin/emerge/.mcp.json`：`{"mcpServers":{"emerge":{"type":"http","url":"https://fpydoc.duckdns.org/mcp/"}}}`。
- `plugin/emerge/skills/emerge/SKILL.md`：手写薄引导（见决策 1，task-agnostic）。
- `plugin/emerge/commands/{run,compare,tune,publish}.md`：薄 slash 入口（通用动词）。
- `.claude-plugin/marketplace.json`（**仓库根**）：目录条目，`source: ./plugin/emerge`。
- `plugin/emerge/README.md`：`/plugin marketplace add qinqiang2000/emerge-api` → `/plugin install emerge@emerge` → 浏览器 OAuth 登录（有 active team 的 emerge 账号）→ `/emerge:run` 等。
- `backend/tests/unit/test_plugin_bundle.py`：plugin.json/marketplace.json/.mcp.json 合法 JSON；marketplace 引用 plugin source 存在；`.mcp.json` URL == `settings.public_base_url + /mcp/`（prod 同步守卫）；SKILL.md 有 frontmatter description。

**Verified（计划）:** `claude plugin validate plugin/emerge`（若 CLI 在）；本地 `claude --plugin-dir plugin/emerge` 加载 → `/emerge:extract` 可见 → OAuth 连上 → 列工具。真机 dogfood：队友机器装一次跑通 extract。

### P3.1 — 收敛 commands（按 dogfood，未来）

dogfood 看队友实际打什么 slash，增删 commands；必要时把 server 侧 `/improve`/`/publish` 路由逻辑映成更聪明的 plugin command（带确认门）。

---

## 红线（遵守）

- **lab=prod 一致**：plugin 只是 transport 入口 + 引导文本，工具体仍是 server 的 `build_emerge_mcp`；不在 plugin 侧重实现任何能力。
- **secret 不进 bundle**：`.mcp.json` 只含公网 URL，无 token（OAuth 在客户端跑）。README 不含任何密钥。
- **薄 skill 不复制 server 深度引导**：避免 drift；深度走 connector 的 MCP prompt（单一真相）。
- **不污染 backend 运行时**：`plugin/` 是纯静态分发物，不被 FastAPI/import 加载；测试只读校验。

## Follow-ups

- marketplace 公开 / 私有访问策略（现 private repo，队友需 git 权限）。
- `.mcp.json` 多环境（prod vs 自建）——现硬编码 prod，将来可参数化或多 plugin 变体。
- P3.1 commands 收敛。
