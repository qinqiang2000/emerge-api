# Users & Teams — 多租户与权限地基

> Plan created 2026-06-03. 引入用户/team/superuser 体系。建立在"无 DB,project=
> 文件夹"之上(`workspace/paths.py`、`config.py::workspace_root`)、复用 `workspace/
> lock.py`(flock)+ `atomic.py`(原子写)+ `ids.py`(短 id)。登录/注册流程参考
> `/Users/qinqiang02/colab/codespace/ai/label-studio`(Django,概念对照非搬代码)。
> 视觉参考 claude.ai。先读 `docs/superpowers/plans/ROADMAP.md`。

**Goal(one sentence):** 每个客户(荣耀/华为/IBM)= 一个 team,team 之间**物理目录隔离**;
用户邮箱+密码登录、凭 team 邀请链接注册入队;一个 superuser 悬于 team 之上,建 team、
看全部数据。

## 决策已定(2026-06-03 与用户敲定)

- **team 创建 = superuser 独占**。一客户一 team,superuser 建好发邀请链接;team 内**无管理员**,
  人人平等、人人可转发同一链接拉人;superuser 是唯一特权方。
- **跨 team 项目共享 = 本期不做**,放下一期(复用 M9.4 `fork_project` clone-at-time 做"模板
  team + 跨 team fork",干净增量;auth 地基先 dogfood)。
- **前端 = 全套**(login/signup + account 菜单 + Settings 弹窗 + superuser team 切换器)。

## Why this shape — team 是 workspace 前缀,不是 DB 里一列

emerge 的骄傲是"无 DB,project=文件夹"。引入 team 最 native 的做法**不是**给
`project.json` 加 `team_id` 然后处处过滤(slug 跨 team 撞、每 route 塞 filter、隔离靠查询),
而是把 **team 做成 workspace 的子目录前缀**:

```
workspace_root/
  _auth/                       ← 全局跨 team:users.json / teams.json
  teams/
    t_honor/   {slug}/...      ← 现有项目目录结构原封不动
    t_huawei/  {slug}/...
  _keys.json                   ← prod API keystore(全局,entry 加 team_id)
```

关键事实:`tools/`、`chat/service.py`、`workspace/paths.py` 所有 helper **已经**是
"接收 `workspace: Path` 第一参、相对它做事",它们**不读 settings**。而 `settings.
workspace_root` 在 **27 个 route 文件、133 处**被直接读取——几乎都是 `settings =
get_settings(); ... settings.workspace_root`。所以只要在 **route 层**引入一个依赖:

```python
def team_workspace(user: User = Depends(current_user)) -> Path:
    return settings.workspace_root / "teams" / user.active_team_id
```

把每个 route 的 `settings.workspace_root` 换成 `ws: Path = Depends(team_workspace)`,
**`tools/`、`chat/`、`paths.py`、`mcp_server` 一行不改**。隔离是**物理目录**(连 agent
的 `cwd` sandbox 边界都自动收紧到本 team,白送),不是查询过滤——对互为竞品的客户更强。
内容缓存 `content_cache_root(ws)` 因为吃 ws 参数,**自动随 team 分桶**(竞品不共享 PDF
渲染缓存的存在性侧信道),零代码改动。

## 数据模型 — 照搬 label-studio 概念,不搬代码

| label-studio (Django) | emerge (FastAPI + FS) | 说明 |
|---|---|---|
| `Organization` | **Team** `{id, name, invite_token, created_by, created_at}` | id = `t_xxx` |
| `Organization.token` | `invite_token`(随机 hash) | 邀请链接 `/signup?token=…` |
| `OrganizationMember` | membership(`team.member_ids` + `user.team_ids`) | 无 owner 权限;`created_by` 仅审计 |
| `User.active_organization` | `user.active_team_id` | claude.ai 的 team 切换器(图3) |

- **User** `{id=u_xxx, email, password_hash(pbkdf2), full_name, display_name, team_ids:[],
  active_team_id, is_superuser, created_at}`。
- **存储** `_auth/users.json` + `_auth/teams.json`,`lock.py` flock 护写 + `atomic.py` 原子写;
  email→user 反查在内存里建(N 很小,几个客户,不需独立索引层)。
- **Session** = starlette `SessionMiddleware`(签名 httpOnly cookie,内置),cookie 只放
  `user_id`,**无会话表**(最 SSU)。secret 走 `EMERGE_SECRET_KEY`(env,不入库)。
- **登录/注册 UX 抄 label-studio**:`?token=` 命中某 team 的 invite_token → 注册后自动入该
  team(`users/views.py::signup` + `organizations/models.py::find_by_invite_url` 的等价物);
  邮箱+密码、**无验证码**(按用户)。

## Hard-rule posture(红线如何处理)

- **不读/不打印/不提交 secrets**:`password_hash` 永不进任何响应/日志;stdlib `pbkdf2_hmac` salted KDF
  (效率第一/安全其次 → 不引 argon2-cffi C 扩展,省 build 摩擦);
  `EMERGE_SECRET_KEY` 走 env,加进 `sdk_settings.json` deny-list 视野外(它本就在 `_auth/`,
  agent cwd 是 team workspace,够不到 `_auth/`)。
- **agent brain ↔ extract LLM 分离不变**:auth 是控制面,不碰五层 LLM。
- **symmetry invariant**:auth 路由是控制面端点、**不是 @tool**(类比 locate/textlayer 的
  route-without-tool),invariant 只强制"@tool⇒route"不强制反向,**无需 `_HTTP_EXEMPT`**。
  不要把 signup/login 包成 agent tool。
- **`_published/` 只读 + prod fast-path**:`/v1/{pid}/extract` 不靠登录态(客户拿 key 调),
  keystore entry 加 `team_id`,route 从 keystore 解析 team workspace → 现有发布解析。明确接线点(T7)。
- **`_auth/` 全局、agent 够不到**:projects 迁入 `teams/` 后,agent cwd=team workspace,
  物理上看不到 `_auth/`。`pid_index` / `orphans` 改为按 team workspace 扫(它们已吃 ws 参数)。

## AI-native auth — 无前端也能玩(同事精神,**核心约束**)

emerge 是"文档处理能力强的**同事**,不绑某界面"(CLAUDE.md 人格红线 + `feedback_ai_native_
api_symmetry` + INSIGHTS #15:UI 必须可被 Claude Code CLI agent 替换而不丢能力)。cookie-
session 只解决**浏览器**;**无前端**时 Claude Code / Claude Desktop cowork 走 HTTP/MCP、**没有
cookie**。若鉴权只认 cookie,整个 headless 面作废。所以鉴权是**双通道**:

- **浏览器** → `SessionMiddleware` 签名 cookie(T2)。
- **headless**(Claude Code CLI 驱 HTTP / Claude Desktop cowork / curl / 二号 CLI client)→
  **Personal Access Token(PAT)**:`Authorization: Bearer <pat>`。PAT 在 Settings 里铸、
  sha256 存哈希(高熵随机串,O(1) 索引,无需慢 KDF)、绑 user(故也绑其 team)。`current_user`
  依赖**同时**接受 cookie 或 bearer——
  一处改,所有 `/lab/*` 路由对 headless agent 立即可用,零额外接线。
- **标准 stdio `mcp_server.py`**(本地、直读 FS、import tools)→ team 经 env `EMERGE_TEAM_ID`
  解析 workspace(`workspace_root/teams/{tid}`);可选 `EMERGE_API_TOKEN`(PAT)定 user。本地
  进程信任边界=谁能跑它,所以 env 驱动即可;hosted/远程 MCP 才强制 PAT。
- **不变量**:加 PAT **不破** symmetry invariant(PAT 是鉴权头,不是新 @tool);反而**保住**它——
  没有 PAT,M11 立的"@tool⇒HTTP route"在多租户下对 headless client 就名存实亡(它登不进来)。

---

## Tasks

### Backend

**T1 — auth 数据模型 + 存储(pydantic + FS,单测先行)**
- `app/auth/models.py`:`User` / `Team` pydantic v2(`extra='forbid'`)。
- `app/auth/store.py`:`_auth/users.json` / `_auth/teams.json` 读写,`flock`(`workspace/lock.py`)
  + 原子写(`atomic.py`)。`create_user` / `get_user_by_email` / `get_user` / `create_team` /
  `get_team` / `add_member` / `set_active_team`。email→user 内存反查。
- `app/auth/passwords.py`:stdlib `hashlib.pbkdf2_hmac`(sha256 + 随机 salt + ~200k iter),
  存 `pbkdf2$<iter>$<salt_hex>$<hash_hex>`。**零新依赖**(效率第一/安全其次)。
- id:复用 `workspace/ids.py` 风格 → `u_xxx` / `t_xxx` / invite_token = `secrets.token_urlsafe`。
- 单测:建用户/建 team/入队/email 反查/密码 verify/重复 email 拒绝。

**T2 — session + PAT 双通道 + `current_user` / `team_workspace` 依赖**
- `app/main.py` 挂 `SessionMiddleware(secret_key=EMERGE_SECRET_KEY, max_age=…, same_site="lax",
  https_only=…)`。**保持登录(用户硬需求):关浏览器不重登** → cookie 必须是**持久长效**(非
  session-only),`max_age` 设长(默认 90 天,env `EMERGE_SESSION_MAX_AGE` 可调)且 **rolling**
  (每次请求刷新过期,活跃用户实质永不掉登录)。starlette 默认 14 天且每响应回写 cookie 已是
  rolling,只需把 `max_age` 调长即可。退出只由显式 `POST /auth/logout`(清 cookie)触发。
- `app/auth/tokens.py`:Personal Access Token——`mint_pat(user) -> (token明文一次性, pat_id)`、
  `verify_pat(token) -> User|None`;**sha256** 存哈希于 `_auth/pats.json`(复用 `keys.py` 哈希思路 +
  O(1) 索引,绑 user 而非 project)。token 形 `emrg_pat_<urlsafe>`。**长效不过期**(只 `DELETE` 吊销)——
  headless 拿一个 token 就能一直用,对齐用户"有单独 token/key 就够了"。
- `app/auth/deps.py`:`current_user() -> User` **双通道**——先看 `Authorization: Bearer <pat>`
  (headless),回落 session cookie(浏览器);皆无 → 401 envelope。`current_superuser()`
  (403 非 superuser);**`team_workspace(user) -> Path`** 返回 `workspace_root/teams/{user.
  active_team_id}`,superuser 用其当前 `active_team_id`(可切)。**bearer 路径下 team 解析**:
  PAT 绑 user→其 `active_team_id`,或请求头 `X-Emerge-Team` 显式覆盖(限该 user 的 `team_ids`)。
- `config.py` 加 `secret_key`、`bootstrap_team_name` 默认值。

**T3 — auth 控制面路由(非 @tool)**
- `app/api/routes/auth.py`:
  - `POST /auth/signup {email, password, full_name, token}` → 校验 token 命中某 team →
    建 user、入该 team、`active_team_id` 设为它、写 session cookie。
  - `POST /auth/login {email, password}` → session cookie。`POST /auth/logout`。
  - `GET /auth/me` → `{user, active_team, teams[]}`(前端 bootstrap;**不含** password_hash)。
  - `PATCH /auth/me {full_name?, display_name?, new_password?}`。
  - `GET /auth/teams/{tid}`(member-only)→ name + invite_link + members(name/email);
    `PATCH /auth/teams/{tid} {name}`(member,无管理员故人人可改名)。
  - `POST /auth/teams/switch {team_id}`(成员或 superuser)→ 改 `active_team_id`。
  - **PAT 管理(headless 用)**:`POST /auth/me/tokens {label}` → 一次性回明文 token(此后只存哈希,
    镜像 `issue_api_key` 的 reveal-once);`GET /auth/me/tokens`(列 label/created/last_used,**不回**
    明文);`DELETE /auth/me/tokens/{pat_id}` 吊销。
- 错误用现行 `{error_code, error_message_en}` envelope。

**T4 — per-team workspace 注入:替换 27 route 文件的 workspace 解析(机械)**
- 每个 `app/api/routes/*.py` 把 `settings.workspace_root` → `ws: Path = Depends(team_workspace)`。
  `chat.py` / `turns.py` 把 `ws` 传进 `chat_turn(workspace=ws, …)`;`publish.py` 走 T7。
- `pid_index.get_index(ws)` / `orphans.cleanup(ws)` 传 team workspace(本就吃 ws 参数)。
- `tools/` / `chat/service.py` / `paths.py` **不改**(`mcp_server.py` 见 T7b)。
- 守护:加一条隔离测——team A 的 cookie 调 `GET /lab/projects` 看不到 team B 的项目;
  跨 team 直接访问 `GET /lab/projects/{B 的 slug}` → 404(物理目录隔离,非 403)。

**T5 — superuser bootstrap + 管理端(superuser-only 建 team)**
- `app/auth/bootstrap.py` + `python -m app.auth.create_superuser`(env 种子
  `EMERGE_SUPERUSER_EMAIL` / 交互式,类比 Django `createsuperuser`)。
- `POST /auth/admin/teams {name}`(superuser-only)→ 建 team + 返回 invite_link。
- `GET /auth/admin/teams` / `GET /auth/admin/users`(superuser-only)→ 全量列表 + 成员。
- superuser 跨 team 看数据 = `team_workspace` 认其 `active_team_id`(可经 `/auth/teams/switch`
  切到任意 team)。

**T6 — 迁移:现有项目 → bootstrap team(幂等)**
- `app/workspace/migrate_tenancy.py`:启动时若无 `teams/`,建 `teams/{bootstrap_team}/`,把
  workspace_root 下所有"含 `project.json` 的目录"+ 现有 `.cache/` + `_keys.json`(原地或标记)
  挪/对齐进 bootstrap team;建 bootstrap team + 挂到 superuser。幂等、可重入(对齐
  `migrate_project_if_needed` 风格)。
- `main.py` startup 钩子里跑(在 `_cleanup_orphan_projects_on_startup` 之前)。

**T7 — keystore + prod fast-path team 作用域**
- `_keys.json` entry 加 `team_id`;`issue_api_key` 盖当前 team。`/v1/{pid}/extract` 从 keystore
  解析 `team_id` → `workspace_root/teams/{team_id}` → 现有 `_published/` 解析。keystore 仍在
  真实根(prod 不靠登录态,单查表最简)。
- 守护测:team A 的 key 调 prod 路由只命中 team A 的发布版本。

**T7b — standalone stdio MCP 的 team 解析(headless cowork 入口)**
- `mcp_server.py` 当前直读 `settings.workspace_root`。改为解析 `workspace_root/teams/
  {EMERGE_TEAM_ID}`(env;缺失则 superuser 的 bootstrap team 或显式报错)。可选
  `EMERGE_API_TOKEN`(PAT)定 user/team。这是 Claude Desktop "cowork"/Claude Code 把 emerge
  当 MCP server 挂载时**选 team 的唯一入口**——没有它,headless 侧落不到正确租户目录。
- README/启动文档补一段:cowork 怎么配 `EMERGE_TEAM_ID`(+ 可选 PAT)。

**T8 — 文档 + INSIGHTS**
- `CLAUDE.md`:加"多租户"一节(team=workspace 前缀;`_auth/` 全局;agent cwd=team workspace)。
- `INSIGHTS.md`:新增——为何 team 做成子目录而非 `project.json` 字段(隔离=物理目录、tools 零改、
  agent cwd 自动收紧);`content_cache_root(ws)` 随 team 自动分桶的副作用。

### Frontend

**T9 — auth store + 启动门禁**
- `stores/auth.ts`:`me`(user+active_team+teams)、`login/signup/logout/switchTeam`、mount 时
  `GET /auth/me`。未登录 → 跳 `/login`。
- `lib/api.ts` 所有 `fetch` 加 `credentials: 'include'`(带 httpOnly cookie)。

**T10 — login / signup 页**
- 抄 label-studio 两屏流程 + claude.ai 视觉。signup 读 `?token=`(无 token 时提示"需邀请链接")。
  邮箱+密码、无验证码。走语义 token(`paper/ink/ochre/...`,见 `tailwind.config.js`),禁 raw color。
- 文案对 finance 终端用户去术语(见 `MEMORY:finance-user-facing-copy`)。

**T11 — account 菜单(图1)**
- 左栏 spine **底部**挂 account chip(`00315ef` 已把"新建项目"移到顶部固定区,底部正好空出):
  avatar + 名字 + popover(email、Settings、Log out)。outside-click/Esc 关。

**T12 — Settings 弹窗(图2)**
- claude.ai 风格侧栏 modal:**General**(avatar/full name/display name)、**Account**(email、改密码)、
  **Developer**(Personal Access Token:铸→一次性 reveal→列 label/last_used→吊销;附 cowork 接入示例
  `Authorization: Bearer …` + `EMERGE_TEAM_ID`)、**Team**(team 名、邀请链接一键复制、成员列表)。
  superuser 多一个 **Admin**(建 team / 列全部 team+user)。

**T13 — team 切换器(图3)**
- account popover 里列 teams + 当前打勾 → `POST /auth/teams/switch` → reload。**仅当 memberships>1
  才显示**(对 superuser 必现;单 team 用户隐藏,保持 SSU)。

### Verify

**T14 — 测试**
- backend:signup/login/session round-trip;**PAT 双通道测**(bearer 与 cookie 命中同一 user;
  `X-Emerge-Team` 越权到非自己 team_ids 被拒);**隔离测**(team A 看不到 team B 项目 / 跨 team 404 /
  prod key 只命中本 team);迁移幂等;superuser 建 team + 切 team。
- frontend:auth store + login + settings(含 PAT reveal-once)+ 切换器渲染。
- 全量:`cd backend && uv run pytest -q`;`cd frontend && npm test && npx tsc -b --noEmit`。

**T15 — live dogfood(human,见 `MEMORY:feedback_milestone_dogfood_handoff`)**
- **浏览器**:superuser 建 team「荣耀」→ 拿邀请链接 → 注册用户 → 登录 → 建项目 → 跑一次 extract;
  另开 team「华为」确认**看不到**荣耀的项目;走 account 菜单 / Settings / 切换器。
- **headless(同事精神验收)**:Settings 铸一个 PAT → `curl -H "Authorization: Bearer …"
  $API/lab/projects` 拿到的正是该 user 的 team 项目、且**与浏览器一致**;用 `EMERGE_TEAM_ID`
  + PAT 起 `mcp_server.py`,确认它落到正确租户目录、能 list/extract。**没有前端也能完成同一套事**。
- 截图/终端记录存 `docs/screenshots/2026-06-03-auth-*.png`。

## Out of scope(明确不做)

- **跨 team 项目共享 / 模板**(下一期,复用 M9.4 fork)。
- **team 内角色/权限分级**(用户明确"无管理员";人人平等)。
- **邮箱验证码 / OAuth / SSO / 找回密码**(按用户"暂时不需要")。
- **计费 / plan / usage**(claude.ai 图里有,emerge 不做)。
- **用户自助建 team**(决策定为 superuser 独占)。
- **per-team 配额 / token 预算**(Lab 侧不预算,见 CLAUDE.md)。
