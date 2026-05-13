# sync-design

从 Anthropic Claude Design API 下载最新设计稿，对比差异，覆盖设计稿文件，同步改动到前端实现，最后 commit。

## 用法
```
/sync-design <URL>
```

## 执行步骤

1. 用 curl 下载 `$ARGUMENTS` 到 `/tmp/design_sync.tar.gz`，解压到 `/tmp/design_sync_extracted/`
2. 与 `docs/design/emerge-api/project/` 逐文件 diff，列出所有差异
3. 覆盖有变化的设计稿文件
4. 分析差异性质并同步到前端：
   - **纯 CSS 改动** → 找到前端对应样式文件，同步改动
   - **结构/组件改动** → 分析影响的前端文件范围，告知用户后询问确认，再同步
5. commit：message 描述具体改动，只 stage 设计稿文件 + 本次实际修改的前端文件
