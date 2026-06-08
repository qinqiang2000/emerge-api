# 2026-06-08 — Cowork / Desktop remote MCP connector

> **Status**: P1 + P1.5 shipped & committed (live ngrok→Cowork dogfood verified in P1.5); 依赖刷新 done (lock bumped, app-boot smoke green, **P2 长杆经实测被 mcp SDK 消掉** — 详见 tip 3 执行记录 + P2 缩范围)，待人跑全套 + dogfood 后 commit；P2–P4 planned
> **Inputs**: research session 2026-06-08 (Anthropic Cowork docs) + tips: (1) 最优集成点为准，不照搬旧约定 (2) 现在就给客户队友用，不只是自己 (3) 评估包升级
> **Closes**: 「同事」北极星的远程落地 —「换前端=换 agent 客户端」从理论变成可连的 connector
> **Does NOT close**: OAuth 一键 onboarding（P2）、plugin marketplace 分发（P3）、工具收敛（P4）

---

## 研究结论（固化，免得丢）

Claude Cowork（2026-02 GA）= "Claude Code power for knowledge work"：同一 agentic 引擎、非开发者 UX、跑在 Anthropic **云 VM** 里。它**不吃「项目目录」**（那是 Claude Code 模型），只认两类入口：① 指给它的本地文件夹（同步进 VM）② **connector = remote MCP server**。

- 自定义集成 = **remote MCP**，传输强制 **Streamable HTTP**（SSE 已弃），鉴权 OAuth 2.0+DCR / custom credentials / 短效 token。一次接，claude.ai / Desktop / Cowork / mobile 全通。
- 本地 stdio MCP（现有 `app/mcp_server.py`）**Cowork 不直接支持**，只能经 Desktop 桥接 → 够不着 Cowork 原生。
- Plugin = 目录包（`.claude-plugin/plugin.json` + `.mcp.json` + `skills/<n>/SKILL.md` + `commands/` + `hooks/`），经私有 marketplace 分发；skill `/` 触发，chat 和 Cowork 共用。

**2×2 的关键认知**：remote 端点建好，整个右列（Desktop/Cowork/web/mobile × remote）**一次点亮**。client 选哪个退化成纯 UX 口味，零额外集成。stdio 降级为本地 dev loopback。

| client × transport | stdio | remote (本 plan) |
|---|---|---|
| Desktop | 现状，dev-only setup | ✅ 中心后端 + UI 加 connector + 跨端 |
| Cowork | ❌ 原生不支持 | ✅ working-session + plugin 分发 |
| web/mobile | ❌ | ✅ 同一 connector |

---

## Goal

emerge 后端能力以 **remote MCP connector** 形态被 Claude Desktop / Cowork / claude.ai / mobile 消费——**多租户、per-request 路由到调用者所属 team**，非技术队友零本地 setup 即可上手（tip 2）。「换前端」从理论变成一条可连的 URL。

---

## 架构决策（tip 1：最优集成点，不照搬 stdio 的 `EMERGE_TEAM_ID` 单团队模型）

1. **多团队 registry，不绑单一 workspace。** stdio server 用 `EMERGE_TEAM_ID` env 在启动时锁死一个 team——remote 场景下 Anthropic 云连过来没有你的 env，且要同时服务多个队友/多个 team。改为 **per-request 解析 team → per-team 缓存一个 MCP server**（工具在 build 时 bake workspace path，和 HTTP route 层一致，绝不用隐藏的 per-request 全局）。
2. **复用 `app.auth.deps` 的双通道鉴权 + `_resolve_team_workspace`。** 不重新实现 PAT 逻辑：connector 请求走 `_authenticate()`，解析顺序 = ① `Authorization: Bearer <pat>` ② `?token=`/`?k=` query PAT ③ session cookie，三者都 resolve 成同一个 `User` 再 `_resolve_team_workspace` 拿到 team 目录。
3. **`?token=` query PAT（SSU 队友 onboarding）。** 让队友把**个人连接 URL**（内嵌自己的 PAT）粘进任何客户端的「Add custom connector」——**无需 OAuth 即可上手**，直接兑现 tip 2。OAuth（P2）是「不把 token 放 URL 里」的升级，不是上手前提。符合 MEMORY:priorities-efficiency-experience-over-security。
4. **生命周期用常驻 task 持有。** `StreamableHTTPSessionManager.run()` 的 anyio task group 不能跨任务进/出，所以每个 team 的 manager 在一个长驻 background task 里 `async with manager.run(): await stop.wait()`，**不放进** FastAPI 的 on_startup/on_shutdown（它们在不同 task 跑）。
5. **stateless=True**：emerge 工具无状态（状态全在磁盘），免 session 跟踪/回收/内存增长。
6. **默认开，`EMERGE_MCP_REMOTE=0` 关。** tenant mode 下 PAT-gated（和 `/lab/*` 同等安全姿态），open mode 下无鉴权（和全 app open mode 一致）——默认开不拓宽攻击面。

---

## Phases

### P1 — remote transport（✅ shipped this turn）

**In:**
- `app/api/mcp_remote.py`：`RemoteMcpRegistry`（per-workspace lazy 缓存 + 常驻 task 生命周期）、`_authenticate`（三通道 + 复用 deps）、`make_mcp_asgi`（ASGI mount，disabled→404 / 401 翻译 / 委派 `handle_request`）。复用 `app.mcp_server.build_mcp_server`（`ui_*`/`ask_user` 过滤 + `emerge-extractor` prompt 暴露）——stdio 与 remote 共用同一 filtered server builder。
- `app/main.py`：`app.mount("/mcp", …)` + 启停 hooks（registry 构造廉价，无 provider/IO，测试下创建无害）。
- `tests/unit/test_mcp_remote.py`：disabled→404、open-mode→root、tenant 无 token→401、header PAT / query PAT → 正确 team 目录、坏 token→401（6 passed）。

**Verified（live，in-process MCP client over Streamable HTTP）:**
- open mode：`TOOL_COUNT 38`（43−5 filtered），`ui_*`/`ask_user` 已滤，`PROMPTS=['emerge-extractor']`。
- tenant mode：无 token→401；`Bearer` header PAT→38 工具（路由到 team workspace）；`?token=` URL PAT→38 工具。
- 回归：symmetry invariant + auth 套件 30 passed；TestClient app-boot green。

**Pending:** commit；真机 dogfood = 本地 `/mcp` → ngrok → 在自己的 Cowork/Desktop「Add custom connector」跑通一次 extract。

### P1.5 — headless discovery tools（✅ shipped；P1 dogfood 暴露）

**根因**：SDK reframe（Step B）砍了 ~23 个 filesystem-wrapper 工具，改让 agent 用内置 Bash `ls`/`cat` 工作区——这**默认了 agent 与工作区共享文件系统**。emerge 自家 chat（agent brain 在服务器，cwd=工作区）和本地 Claude Code 成立；**远程 MCP 不成立**：Cowork 的 Bash 在它自己的云沙箱，看不到服务器磁盘。2026-06-08 首次 Cowork dogfood（team `发票云空间`，PAT 路由正确生效）实锤：agent 「没有列出所有项目的接口」——`list_projects` 只是撞到的第一个，这是整类"发现/读取"工具对任何不共享 FS 的客户端集体隐形。

**修法**：在 **headless 层**（`build_emerge_mcp(headless=True)`，stdio + remote 都经 `build_mcp_server` 传入）加回三个只读发现工具 `list_projects` / `list_docs` / `read_schema`；emerge 自家 chat 走默认 `headless=False`，零影响。这是 `_HEADLESS_EXCLUDE`（headless 减 `ui_*`）的**加法孪生**。三者 HTTP twin 早已存在（`GET /lab/projects` · `.../docs` · `.../schema/raw`），补进 `_TOOL_HTTP_MAP` → 对称契约不破。`_discover_tools()` 正则扫 `__init__.py` 源码，故 `@tool` 常驻源码、仅注册受 flag 控制。

**Verified**：单测 `test_discovery_tools_headless_only`（headless 46 工具含 3 发现 / chat 43 无泄漏）；symmetry 3 passed；广测 394 passed 零回归。Live remote（PAT over Streamable HTTP）`call_tool("list_projects")` → 真实列出 team 工作区项目 `[(远程发现验证, empty)]`。

**Follow-up（P1.6 候选，未做）**：完整 reconcile —— Step B 砍的 23 个里还有哪些"读取/写入"在远程无 FS 下隐形（`get_prediction`/`get_reviewed`/`list_prompts`/`list_models`/`create_prompt`/`write_model`…）。本期只解锁 extract→review 最小闭环的发现三件；写操作与其余读取按 dogfood 反馈增量回归 headless 面。

### P2 — OAuth 2.0 + DCR（planned；**长杆已被 SDK 消掉**，见 2026-06-09 依赖刷新）

让 Cowork/Desktop「Add custom connector」用**登录**而非手贴 PAT onboard 队友。需要：authorization server（`/authorize` `/token` `/register` DCR）、consent、token↔user 映射（复用 PAT 存储层）、`WWW-Authenticate` + protected-resource metadata 让客户端发现。回调 `https://claude.ai/api/mcp/auth_callback`。企业可走 admin `managedMcpServers` + `headersHelper` 注入 per-user 短效 header，绕过 per-user OAuth。

**重大缩范围（2026-06-09 实测）**：authorize/token/register/revoke/metadata **整套服务端脚手架已在 `mcp` SDK 里**（`mcp.server.auth`，刷新前 1.27.0 就有，非本次 bump 新带）。P2 不再手搓协议，只剩 4 件 emerge-specific 黏合：

1. **实现 `OAuthAuthorizationServerProvider` Protocol**（`mcp.server.auth.provider`）——9 个方法 `get_client`/`register_client`/`authorize`/`load_authorization_code`/`exchange_authorization_code`/`load/exchange_refresh_token`/`load_access_token`/`revoke_token`，全部后端到 `_auth/{users,pats,clients}.json`（复用现有 keystore 模式；新增 oauth client + code 短效存储）。
2. **mount 路由**：`create_auth_routes(provider, issuer_url, client_registration_options=ClientRegistrationOptions(enabled=True), …)` → `/authorize` `/token` `/register` `/revoke` + `/.well-known/oauth-authorization-server`；`create_protected_resource_routes(...)` → `/.well-known/oauth-protected-resource`（RFC9728，客户端发现入口）。
3. **consent 页**：`authorize()` 里渲染最小同意屏（复用现有 session cookie 认 user → 授权该 client）。这是唯一真正要写 UI 的部分。
4. **把 `TokenVerifier` 接进 `/mcp` 传输**：现 `_authenticate` 的三通道加第 4 路「OAuth bearer」（`ProviderTokenVerifier(provider).verify_token` → user → `_resolve_team_workspace`），与 PAT bearer 并列；`WWW-Authenticate` 头指向 protected-resource metadata。

净效果：P2 从「自建 AS」降级为「实现一个 Protocol + 一个 consent 页 + 接线」。`?token=` query PAT 保留作 dev/curl 后路。

### P3 — plugin bundle（planned）

`emerge_extractor.md` → `skills/emerge-extractor/SKILL.md`；`.mcp.json` 指向 remote connector；`.claude-plugin/plugin.json`。放私有 marketplace，队友一键装得 `/emerge-*` slash（chat + Cowork 共用）。

### P4 — 工具收敛（planned）

38 个给非技术队友偏多。靠 skill prompt 引导 + per-tool policy（`ask`/`blocked`）把高危/低频收起，暴露给 Cowork 的核心动词 ~10 个。

---

## 红线（遵守）

- **lab=prod 一致**：remote 复用同一 `build_emerge_mcp` 工具体，工具内绝不递归回 SDK；agent brain 仍是外部 Claude 客户端。
- **prod 产物落真实根**：`freeze_version`/`issue_api_key` 内部已写真实根 keystore/_published；remote 传给工具的是 team workspace（和 HTTP route `current_ws()` 同值），不改这些工具，红线不破。
- **`interface=headless`**：Cowork/Desktop 即 headless 分支，`ui_*` 已被过滤（headless 无意义），rendering contract 不变。
- **bbox 永不进 prompt**：transport 层不碰 evidence/坐标。
- 不新增根级 `_` sentinel 目录（无 orphan sweep 风险）；无物理删除。

---

## tip 3：包升级评估

当前 `mcp==1.27.0` 已含 `streamable_http_manager` + `TransportSecuritySettings` + stateless——P1 在现版本上一次写成，**升级不会省工**。`claude-agent-sdk>=0.2.87` 的 `create_sdk_mcp_server` 已复用。结论：**P1 不需要升级**；建议把「全量依赖刷新」作为**独立一次变更**（跑全套 + dogfood）放在 P2/OAuth 之前，别和功能耦合（升级风险 + 功能风险不叠加）。届时关注新 SDK 是否带 OAuth helper，可能省 P2 的工。

### 依赖刷新执行记录（2026-06-09，P2 前置，独立变更）

`uv lock --upgrade` + `uv sync --all-groups`，21 个包 bump（均 patch/minor，无 major 破坏跳跃）。重点：

| 包 | 旧 → 新 | 关注面 |
|---|---|---|
| claude-agent-sdk | 0.2.87 → 0.2.94 | agent brain；无 server-OAuth helper（client 侧 only） |
| mcp | 1.27.0 → 1.27.2 | patch；**server-side OAuth 框架早在 1.27.0 就有**（见下） |
| starlette | 1.0.0 → 1.2.1 | auth deps 用 Request/session——app-boot 冒烟通过 |
| fastapi | 0.136.1 → 0.136.3 | patch |
| google-genai | 2.0.0 → 2.8.0 | provider/gemini |
| uvicorn | 0.46.0 → 0.49.0 | 服务器 |
| pyjwt | 2.12.1 → 2.13.0 | P2 OAuth 若发 JWT 用得上 |

**OAuth-helper 关注点 → 已结论（tip 3 的核心问句）**：`claude-agent-sdk 0.2.94` 是 **client 侧**，不带 server-OAuth helper。但 server-side 整套 OAuth AS 脚手架在 **`mcp` SDK** 里（`mcp.server.auth.{provider,routes,settings,handlers/*}`），**且刷新前 1.27.0 就已存在**——所以诚实地说：本次刷新的价值是**版本 currency + 把 P2 缩范围这件事查实**，而非升级"解锁"了 OAuth。P2 详细缩范围已写进 P2 章节。

**验证（不跑全套——本机由人跑 + dogfood）**：app boot 120 routes；`starlette 1.2.1 / fastapi 0.136.3 / mcp 1.27.2 / uvicorn 0.49.0 / claude-agent-sdk 0.2.94` 下 `app.main`、`app.api.mcp_remote`、`mcp.server.auth.*`、`mcp.server.streamable_http_manager` 全部 import OK。`PromptVariant` 的 `schema` shadow `UserWarning` 是既存项（裸 import 没走 app 启动 filter），非升级回归。

**Pending（人来收口）**：① `uv run pytest -v` 全套绿 ② ngrok→Cowork dogfood 复跑一次 extract ③ 两者通过后 commit 这次独立变更（`pyproject.toml` 实际未改 pin，仅 `uv.lock` 变）。

---

## Follow-ups

- P1 真机 dogfood（ngrok→Cowork）。
- `?token=` 在 URL 里有日志泄露面——P2 OAuth 落地后把它降级为「仅 dev/curl」或加开关。
- per-team manager 数量上限 / 空闲回收（当前随 team 数线性增长，handful 量级无虞）。
- `issue_api_key` 在 remote 多租户下应默认绑定 authed user，而非 `user_id="default"`（小口子，P2 一起收）。
