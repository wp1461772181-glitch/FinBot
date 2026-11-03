# 第三方声明

## bloub（`frontend/src/bloub/`）

- 项目：https://github.com/jeremy-prt/bloub（锁定提交 `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`）
- 用途：bot 头像的动画引擎（`src/bot/`，原样 vendor；不含其 Vue 组件）；形状/颜色/表情/状态目录全量取自同一引擎源（8 / 12 / 16 / 14 + swirl）
- 另借鉴（按 React 与本项目主题令牌重写，非复制）：定制面板的版式与选中态样式（`Customizer.vue`、`BotTile.vue`）→ `frontend/src/BloubCustomizer.tsx`、`grok.css` 的 `.bloub-*`；品牌标记与站点 favicon 为系统原版（三姿势 logo），不使用 bloub 素材
- 许可：MIT License，Copyright (c) 2026 Jérémy Perret。完整许可文本见 `frontend/src/bloub/LICENSE`
