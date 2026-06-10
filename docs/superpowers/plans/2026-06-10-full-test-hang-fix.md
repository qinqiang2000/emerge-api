# 2026-06-10 — full test 卡死根治（SSE turn 测试死锁 + 永不再裸挂）

> **Status**: 📝 plan
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
