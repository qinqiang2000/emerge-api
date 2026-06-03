# Users & Teams — dogfood 引导

> 验收 `2026-06-03-users-and-teams.md`。目标:浏览器多租户隔离 + headless PAT 同权。
> 没有内置默认 superuser——跑 bootstrap 前是 open mode(零鉴权,= 旧行为)。

## 0. 起服务

```bash
./dev.sh restart        # backend :8080 + frontend :5173
```

## 1. 建 superuser(翻成 tenant mode)

```bash
cd backend
# 交互式(密码不回显):
uv run python -m app.auth.create_superuser
#   Superuser email: root@emerge.dev
#   Password: ********
# 或 env 种子(免交互):
EMERGE_SUPERUSER_EMAIL=root@emerge.dev EMERGE_SUPERUSER_PASSWORD=secret \
  uv run python -m app.auth.create_superuser
```

跑完:`/lab/*` 开始强制鉴权,现有项目已幂等迁入 bootstrap team。

## 2. superuser 建客户 team(浏览器)

1. `http://localhost:5173` → 用 superuser 登录。
2. 左下 account chip → **Settings → Admin** → 「创建团队」输入 `荣耀` → 复制其邀请链接。
3. 再建一个 `华为`,复制其邀请链接。

## 3. 成员注册入队 + 隔离验证

1. **隐身窗口**打开`荣耀`邀请链接(`/?invite=...`)→ 注册 `dev@honor.com` → 自动入荣耀。
2. 建项目 `honor-proj` → 跑一次 extract。
3. **另一隐身窗口**打开`华为`邀请链接 → 注册 `dev@huawei.com` → 建 `huawei-proj`。
4. **断言**:honor 窗口的项目列表只有 `honor-proj`,看不到 `huawei-proj`(物理目录隔离)。
   磁盘核对:`ls backend/workspace/teams/*/`,两个 team 各一棵子树。

## 4. headless 同权(同事精神核心验收)

1. 回 honor 窗口 → **Settings → Developer** → 「创建令牌」→ 复制 `emrg_pat_...`(只显一次)。
2. 终端,**无 cookie、只带 bearer**:

```bash
curl -s -H "Authorization: Bearer emrg_pat_xxx" http://localhost:8080/lab/projects
# 期望:只返回 honor-proj,与浏览器一致
curl -s http://localhost:8080/lab/projects        # 无 token → 401
```

3. (可选)把 PAT + `EMERGE_TEAM_ID=<honor team_id>` 配进 Claude Desktop/Code 的 MCP server,
   确认 cowork 落到荣耀租户、能 list/extract。

## 5. 持久登录 + 切换器

- 关浏览器重开 `:5173` → 仍登录(90 天 rolling cookie),只有点 **Log out** 才退。
- superuser 的 account 菜单里出现 team 切换器(成员>1 才显示)→ 切到 `华为` → 整页 reload 到该租户。

## 通过标准

honor 看不到 huawei 项目 · 跨 team 直接访问 404 · PAT 与浏览器同权、无 token 401 ·
关浏览器不重登 · 截图存 `docs/screenshots/2026-06-03-auth-*.png`。
