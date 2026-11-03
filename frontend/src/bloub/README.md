# bloub（第三方，已 vendor）

本目录下的 `*.ts` 是 [jeremy-prt/bloub](https://github.com/jeremy-prt/bloub) 的 `src/bot/` 引擎，**原样复制、未改动**
（框架无关、无时钟的 TypeScript 引擎，`BotEngine.sample(t)` 是时间的纯函数）。

- 来源：https://github.com/jeremy-prt/bloub
- 锁定提交：`b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`（main）
- 许可：MIT，Copyright (c) 2026 Jérémy Perret，见同目录 `LICENSE`
- 未带入：该项目的 Vue 组件与 `*.test.ts`（vitest）。React 侧的渲染见 `../BloubAvatar.tsx`
- 升级时整体覆盖本目录的 `*.ts`，不要手改这些文件

第三方声明汇总见仓库根目录 `THIRD_PARTY_NOTICES.md`。
