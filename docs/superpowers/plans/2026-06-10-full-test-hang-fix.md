# 2026-06-10 — full test 卡死根治（SSE turn 测试死锁 + 永不再裸挂）

> **Status**: ✅ T1–T3 done（T1 护栏主会话落地；T2/T3 子代理 2026-06-10 完成，根因见下）

## 根因记录（T2 结论，2026-06-10）

**不是依赖漂移。** 首坏 commit = `5829668`（feat(headless): interface signal，2026-06-02）。两层叠加：

1. **测试 fake 签名漂移（触发器）**：`5829668` 给 `turns.py::_start_turn_for` 的
   `svc.chat_turn(...)` 调用加了 `interface=body.interface`，但
   `test_chat_turns_lifecycle.py` / `test_turns_reattach_after_finish.py` 里的
   `_FakeChatService.chat_turn` 签名没加 `interface` → `runner_factory()` 抛
   `TypeError`。
2. **产品真 bug（死锁机制）**：`turn_registry.py::_run_turn` 的
   `runner = runner_factory()` 在 **try 之外**——factory 同步抛异常时 task 带异常
   死掉，`entry.status` 永远卡 RUNNING、sentinel 永不广播 → SSE `gen()` 在
   `await queue.get()`（turns.py:384）无限等待，TestClient portal future 永不
   resolve；且该 chat 永远 409 `turn_already_active`（prod 同样会中招）。

**取证链**：依赖 overlay 二分（starlette 1.0.0 / sse-starlette 3.4.2 / 双旧 /
pytest-asyncio 1.3.0 全部仍死锁）排除版本漂移；gc 协程栈 dump 定位 `gen()` 悬挂点 +
`turn-xxx` task `done=True` 但无 sentinel；独立复刻脚本（fake 恰好带 `interface`
形参）通过 → 锁定签名不匹配。注：repo **没有 CI**（无 `.github/`），旧 memory
"CI 里能过" 无据。

**修复**（不改产品语义，只补健壮性）：
- `app/chat/turn_registry.py`：`runner_factory()` 移入 try，sync 异常 →
  `status=error` + 标准 envelope + sentinel 广播（runner=None 时 aclose 跳过）。
- 两个测试 fake 补 `interface: str = "browser"` 形参。
- 新增回归单测 `test_factory_exception_flips_error_and_sends_sentinel`
  （tests/unit/test_turn_registry.py）。

**验证**：两文件各 3 连跑全绿（lifecycle ~1.3s×3、reattach ~0.8s×3）；全量
`uv run pytest -n 8 --dist loadfile -q` → **1471 passed, 2 skipped, 1 xfailed,
10.68s**，零 hang 零 Timeout。

**T3 体检**：`--durations=25` 最慢 3.82s（`test_extract_one_reads_schema_from_active_prompt`），
无 >10s 测试，全量 11s ≪ 5 分钟目标，无需放宽任何 timeout。
> **现象**: 全量 `uv run pytest` 经常 1h+ 跑不完。今日取证:卡死点是 `tests/integration/test_chat_turns_lifecycle.py::test_start_then_stream_full_turn`,**非沙箱也死锁**(0% CPU),**单独跑该文件也死锁**(排除跨测试污染)。此前 memory 记"沙箱才挂"已过时。
> **证据**(faulthandler SIGABRT dump,2026-06-10):
> - 主线程:阻塞在 `_drain_stream_to_eof` → `client.stream(GET …/turns/{tid}/stream)`,portal future 永不 resolve。
> - portal 事件循环线程:**selector 空转**——loop 活着但 SSE generator 无事可做,turn 后台 task 也没在跑。
> - 测试全 mock(fake chat service),无真 LLM/网络 → 纯编排死锁:POST start spawn 的 asyncio.Task 与 GET stream 的 generator 在 buffered TestClient portal 下互等。
> - 该文件 2026-05-19(M11)写成时通过 → 嫌疑首推依赖漂移(starlette/anyio/httpx 版本),其次 turn_registry 后续改动。

## 两层修复(都要):根因修 + 护栏

### T1 — 护栏先行:pytest-timeout(让"挂死"永远变成"秒级失败+堆栈")
- `uv add --dev pytest-timeout`;`pyproject.toml` pytest 配置加 `timeout = 120`、`timeout_method = "thread"`(faulthandler 风格 dump,正是今天手动 SIGABRT 干的事,自动化它)。
- 个别合法慢测试(若有)用 `@pytest.mark.timeout(300)` 显式放宽——**显式**,不许全局放水。
- 这一步独立可部署:先落,任何后续回归立刻现形而不是吃掉一小时。

### T2 — 根因定位与修复(turns lifecycle 死锁)
诊断顺序(子代理照做):
1. `git log --oneline -- backend/app/api/routes/turns.py backend/app/chat/turn_registry.py` + `uv.lock` 近期 starlette/anyio/httpx 版本变化;`git stash`/checkout 旧 commit 复跑该文件,二分是"代码改动"还是"依赖漂移"。
2. 在 T1 的 timeout dump 下逐个跑该文件 6 个测试,确认是全死还是个别死;对比 `test_chat_routes_unbound.py` 等仍活着的 SSE 测试,找差异(blocking portal 用法/REGISTRY task spawn 时机)。
3. 修复方向按根因:
   - 若依赖漂移:优先改**测试编排**适配新行为(如 portal 上显式 `portal.call` 驱动 task、或 stream 消费改 `httpx.ASGITransport` + 异步消费),不为测试去改产品代码;锁版本是最后手段且要在 INSIGHTS 记一笔。
   - 若产品代码真有 race(turn task 只在有订阅者时才被调度之类):那是 prod bug,修产品代码,测试不动。
4. 修完:该文件单独跑 <30s 通过;连续跑 3 遍稳定(防 flaky)。

### T3 — 全量耗时体检(防"下一个一小时")
- T1/T2 落地后跑全量,`--durations=25` 存档进本 plan 的 Status 注;>10s 的测试逐个看是否在等真实超时(如 provider retry sleep)——能 mock 时间的 mock,不能的标 `@pytest.mark.timeout` 放宽并注明。
- 目标:**全量 ≤5 分钟**(1196+ 测试,今天定向子集 47 个 0.6s,推算合理)。
- 在根 CLAUDE.md 测试一行补:"全量必须分钟级,新增 >10s 的测试要写理由"。

### T4 — memory/文档更新
- 更新 memory `project_sse_testclient_hangs_in_sandbox`:不是沙箱专属——是 turns SSE 测试死锁(已修/护栏已加),沙箱告诫保留但降级。
- INSIGHTS.md 加 trap note:TestClient(blocking portal) + 后台 asyncio.Task + SSE 的组合对依赖版本敏感,动 starlette/anyio 后必跑 `test_chat_turns_lifecycle.py`。

## 验收
- `uv run pytest -q` 全量在本机 ≤5 分钟完成,零 hang。
- 人为引入一个 `await asyncio.sleep(999)` 的假死测试 → 120s 内自动失败并打印全线程堆栈(护栏自证)。

## 红线
- 不许用"跳过该文件"当修复(它守的是 M11 turn-as-resource 契约,detach/reattach/cancel 都靠它);deselect 只允许作为修复期间的临时部署门禁,修复 PR 必须恢复。
- 修测试不改产品语义;若必须改产品代码,先确认是真 race 并在 plan 里记根因。
