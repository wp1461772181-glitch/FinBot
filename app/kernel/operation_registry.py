"""Every route that changes data, and what the assistant's ``act`` does about it.

``tests/test_operation_registry.py`` walks the app's routes and fails when a ``POST/PUT/PATCH/DELETE`` route is not listed here, so a new
route cannot ship without somebody deciding.  Each entry is one of

- ``{"operation": name}`` (or a tuple of names): ``act`` covers it, and the operation goes through the same write path the route does;
- ``{"exempt": reason}``: left out on purpose, with the reason in one Chinese line (the reason a later reader will check against);
- ``{"gap": reason}``: nobody has decided to leave it out, it just is not built; kept visible so it is not mistaken for a decision.

Source: docs/reports/2026-11-mutating-endpoints.md (section 1), updated for stage 3a.
"""
from __future__ import annotations


def _op(*names: str) -> dict:
    return {"operation": names[0] if len(names) == 1 else tuple(names)}


def _no(reason: str) -> dict:
    return {"exempt": reason}


def _gap(reason: str) -> dict:
    return {"gap": reason}


_PAGE_ONLY_STATE = "页面上的界面状态，不是 owner 要交代给助手的事"
_CREDENTIAL = "凭据由 owner 自己在页面里放，不经过助手"
_KEY = "带模型密钥，密钥只由 owner 在页面里放"
_CHANNEL_BINDING = "绑定或解绑渠道要 owner 自己在手机上完成，不由助手代办"
_LEGACY = "遗留的旧接口，已被 v2 取代，不开放给助手"
_CONFIRM_BY_OWNER = "这是 owner 自己的同意动作（点确认/跳过/稍后），不能由助手代点"
_READ_ONLY_TEST = "只读的连通或试跑，不改任何数据"

OPERATION_REGISTRY: dict[tuple[str, str], dict] = {
    # 对话与登录
    ("POST", "/agent-chat/stream"): _no("它就是助手本身，不是助手要操作的对象"),
    ("POST", "/agent-chat/hello"): _no("只读的连通测试，游客可用，不改数据"),
    ("POST", "/agent-chat/messages"): _no("游客直连通道，不带工具，不改 owner 的数据"),
    ("POST", "/agent-chat/models"): _no("只列出服务商的可用模型，要调用方自己的密钥，不改数据"),
    ("POST", "/agent-chat/conversations/{conversation_id}/cancel"): _no("停止按钮；回合在跑时助手本身无法响应"),
    ("POST", "/agent-chat/conversations/{conversation_id}/compact"): _no("已有「/压缩」命令，属于对话控制"),
    ("POST", "/agent-chat/bots/{bot_id}/compact"): _no("已有「/压缩」命令，属于对话控制（Telegram 按 bot 找对话线）"),
    ("PATCH", "/agent-chat/conversations/{conversation_id}"): _no("对话改名和归档不开放：无需求证据，价值低，在页面上做"),
    ("PUT", "/agent-chat/conversations/{conversation_id}/turns/{turn_id}/feedback"): _op("rate_answer"),
    ("DELETE", "/agent-chat/conversations/{conversation_id}/turns/{turn_id}/feedback"): _op("rate_answer"),
    ("POST", "/agent-chat/personal-login"): _no("登录；owner 凭据不经过助手"),
    # Bot
    ("POST", "/agent-chat/bots/{bot_id}/read"): _no(_PAGE_ONLY_STATE),
    ("POST", "/agent-chat/bots"): _op("create_bot"),
    ("PATCH", "/agent-chat/bots/{bot_id}"): _op("update_bot"),
    ("DELETE", "/agent-chat/bots/{bot_id}"): _no("删除 bot 会带走它的整条对话线，不可恢复，只在页面上由 owner 亲手做"),
    # 模型目录与角色
    ("POST", "/agent-chat/model-catalog"): _no("添加模型条目会带密钥，密钥只由 owner 在页面里放"),
    ("POST", "/agent-chat/model-catalog/test"): _no(_READ_ONLY_TEST + "，要用到条目的密钥"),
    ("POST", "/agent-chat/model-catalog/models"): _no("只列出服务商的可用模型，要用到密钥，不改数据"),
    ("PATCH", "/agent-chat/model-catalog/{name}"): _no("改条目、换密钥、重命名都涉及密钥，只在页面上做"),
    ("DELETE", "/agent-chat/model-catalog/{name}"): _no("删除条目会带走已存的密钥，只在页面上做"),
    ("PUT", "/agent-chat/model-catalog/default"): _op("set_default_model"),
    ("PUT", "/agent-chat/model-roles/{role}"): _op("set_model_role"),
    # 技能
    ("POST", "/agent-chat/skills"): _op("save_skill"),
    ("PATCH", "/agent-chat/skills/{skill_id}"): _op("manage_skill"),
    ("POST", "/agent-chat/skills/{skill_id}/enabled"): _op("manage_skill"),
    ("DELETE", "/agent-chat/skills/{skill_id}"): _op("manage_skill"),
    ("POST", "/agent-chat/skills/{skill_id}/copy"): _no("界面便利功能；用「保存技能」能得到同样的结果"),
    ("POST", "/agent-chat/skills/import/preview"): _no("只预览一份 markdown 技能文件，不写数据"),
    ("POST", "/agent-chat/skills/import"): _op("save_skill"),
    # 画像与记忆
    ("POST", "/agent-chat/profile"): _op("remember"),
    ("PATCH", "/agent-chat/profile/{item_id}"): _no("不开放改记忆文字：要改可先忘掉再记一条，直接改写会让「这是用户原话」失真"),
    ("POST", "/agent-chat/profile/{item_id}/confirm"): _no("把推断项确认为明示本来就是 owner 亲手点的动作，让模型代点会抹掉这个区别"),
    ("POST", "/agent-chat/profile/{item_id}/restore"): _no("本人在页面上恢复"),
    ("DELETE", "/agent-chat/profile/{item_id}"): _op("forget"),
    ("POST", "/agent-chat/views/{symbol}"): _op("record_view"),
    ("POST", "/agent-chat/views/{symbol}/drop"): _op("drop_view"),
    ("POST", "/agent-chat/views/{view_id}/restore"): _no("本人在页面上恢复"),
    ("DELETE", "/agent-chat/views/{view_id}"): _no("网页上本人删除一条历史，不开放给助手"),
    # 研究队列与例行任务
    ("PUT", "/agent-chat/research-queue"): _op("add_to_research_queue", "remove_from_research_queue"),
    ("POST", "/agent-chat/tasks"): _op("create_routine"),
    ("PATCH", "/agent-chat/tasks/{task_id}"): _op("update_routine"),
    ("DELETE", "/agent-chat/tasks/{task_id}"): _op("delete_routine"),
    # 收件箱与确认
    ("POST", "/agent-chat/inbox/{item_id}/status"): _no(_PAGE_ONLY_STATE),
    ("POST", "/agent-chat/inbox/{item_id}/card"): _no("系统机制：把待确认建议变成确认卡，本身不是 owner 的意图"),
    ("POST", "/agent-chat/inbox/{item_id}/confirm"): _no(_CONFIRM_BY_OWNER),
    ("POST", "/agent-chat/routines/{item_id}/confirm"): _no(_CONFIRM_BY_OWNER + "（同一处理函数的另一个路径）"),
    ("POST", "/agent-chat/routines/confirmations/{item_id}/action"): _no(_CONFIRM_BY_OWNER + "（同一处理函数的第三个路径）"),
    ("POST", "/finbot/routines/{routine_id}/confirm"): _no(_CONFIRM_BY_OWNER + "（通知里直接点；必须带这张卡自己的 action_token）"),
    # 新闻源
    ("PUT", "/agent-chat/news-sources/push-settings"): _gap("推送摘要字数上限；无对话证据，价值很低，尚未做"),
    ("POST", "/agent-chat/news-sources"): _no("新增新闻源写入的是一个网址，容易被网页内容诱导；有人开口要再说"),
    ("POST", "/agent-chat/news-sources/{source_id}/enabled"): _gap("启用/停用新闻源；无对话证据，尚未做"),
    ("POST", "/agent-chat/news-sources/{source_id}/dry-run"): _no("只试抓一页，不写配置"),
    ("POST", "/agent-chat/news-sources/{source_id}/repair"): _no("维护类动作，有每小时一次的冷却，由页面按钮触发"),
    ("DELETE", "/agent-chat/news-sources/{source_id}"): _gap("删除新闻源；无对话证据，尚未做"),
    # 后台模型、通知渠道、Telegram、Pushover
    ("PUT", "/agent-chat/background-model"): _no(_KEY),
    ("DELETE", "/agent-chat/background-model/key"): _no("清除已存的后台密钥，属于密钥管理"),
    ("PUT", "/agent-chat/channels"): _op("set_channel_prefs"),
    ("POST", "/agent-chat/role-templates/{template}/preview"): _no("只预览模板会写什么，不写数据"),
    ("POST", "/agent-chat/role-templates/{template}/apply"): _op("apply_role_template"),
    ("POST", "/agent-chat/role-templates/applications/{application_id}/undo"): _op("undo_role_template"),
    ("POST", "/agent-chat/telegram/token"): _no(_CREDENTIAL),
    ("POST", "/agent-chat/telegram/bind"): _no(_CHANNEL_BINDING),
    ("POST", "/agent-chat/telegram/unbind"): _no(_CHANNEL_BINDING),
    ("PUT", "/agent-chat/pushover"): _no(_CREDENTIAL),
    ("DELETE", "/agent-chat/pushover"): _no(_CREDENTIAL),
    ("POST", "/agent-chat/bots/{bot_id}/telegram/token"): _no(_CREDENTIAL),
    ("POST", "/agent-chat/bots/{bot_id}/telegram/bind"): _no(_CHANNEL_BINDING),
    ("POST", "/agent-chat/bots/{bot_id}/telegram/unbind"): _no(_CHANNEL_BINDING),
    ("DELETE", "/agent-chat/bots/{bot_id}/telegram"): _no(_CREDENTIAL),
    # 持仓
    ("POST", "/agent-chat/portfolio/transactions"): _op("record_trade"),
    ("DELETE", "/agent-chat/portfolio/transactions/{transaction_id}"): _op("delete_transaction"),
    ("PUT", "/agent-chat/portfolio/plans/{symbol}"): _op("set_position_plan"),
    ("PUT", "/agent-chat/portfolio/cash"): _op("set_available_funds"),
    # 盯防规则
    ("POST", "/agent-chat/watch-rules"): _op("set_watch_rule"),
    ("PATCH", "/agent-chat/watch-rules/{rule_id}"): _op("set_watch_rule"),
    ("DELETE", "/agent-chat/watch-rules/{rule_id}"): _op("delete_watch_rule"),
    ("PATCH", "/agent-chat/watch-presets/{key}"): _op("set_watch_preset"),
    ("POST", "/agent-chat/watch-presets/{key}/reset"): _op("set_watch_preset"),
    ("PUT", "/agent-chat/alert-settings"): _op("set_alert_settings"),
    ("POST", "/backstage/feedback"): _op("rate_alert"),
    # 预测
    ("POST", "/v2/forecast-jobs"): _op("forecast"),
    ("POST", "/v2/historical-replays"): _op("start_historical_replay"),
    ("POST", "/v2/forecast-versions/{version_id}/revision-jobs"): _op("revise_forecast"),
    ("POST", "/forecasts"): _no("遗留的 Week 1 假数据接口，不开放"),
    ("POST", "/forecast-runs"): _no(_LEGACY),
    ("POST", "/research-runs"): _no("遗留的旧研究工作流，不开放"),
    ("POST", "/forecast-refresh-runs"): _no("遗留的旧滚动刷新，不开放"),
    ("POST", "/evidence-revisions/{symbol}"): _no("遗留的旧版证据修订，已被「修订预测」取代"),
    # 资料、SEC、行情、分析、翻译
    ("POST", "/filing-inventories/{symbol}/scan"): _op("scan_official"),
    ("POST", "/filing-inventories/{symbol}/{accession_number}/fetch"): _op("fetch_sec", "refresh_sec"),
    ("POST", "/filing-inventories/{symbol}/{accession_number}/review"): _op("review_filing"),
    ("POST", "/market-data/{symbol}/initialize"): _op("initialize_prices"),
    ("POST", "/uploaded-evidence/{symbol}"): _op("save_material_evidence", "ingest_web_source"),
    ("POST", "/v3/materials/{source_type}/{source_id}/analysis-jobs"): _op("analyze"),
    ("PUT", "/v3/materials/analysis-settings"): _no("设置分析模型可带密钥，密钥只由 owner 在页面里放"),
    ("DELETE", "/v3/materials/analysis-settings"): _no("清除分析模型设置，属于同一套密钥配置"),
    ("POST", "/v3/material-analyses/{analysis_id}/localization"): _op("translate_content"),
    ("POST", "/v2/forecast-versions/{version_id}/brief-localization"): _op("translate_content"),
    # 知识库
    ("POST", "/knowledge/retrieval-test"): _no("只做一次检索测试，不改数据；读取类工具已够用"),
    ("POST", "/knowledge/import"): _op("import", "import_sources"),
    ("POST", "/knowledge/index"): _op("index"),
    ("POST", "/knowledge/documents/{document_id}/withdraw"): _op("withdraw_knowledge_document"),
    ("POST", "/knowledge/documents/{document_id}/retry"): _op("retry_document_index"),
    ("POST", "/knowledge/candidates/{candidate_id}/review"): _op("review_knowledge_candidate"),
    # 公开标记、哨兵、本机配置
    ("POST", "/agent-chat/public-marks/review"): _no("人工复核本身必须是人的判断，不能由模型代做"),
    ("POST", "/agent-chat/public-marks/pause"): _no("安全熔断开关，只给操作员"),
    ("POST", "/agent-chat/public-marks/resume"): _no("恢复展示要人亲自给出回放引用"),
    ("POST", "/agent-chat/internal/sentinel/events"): _no("机器接口，只收回环地址加密令，不是用户操作"),
    ("PUT", "/agent-chat/local-model-profiles"): _no("只在本机开发模式开启，公开模式下直接 404"),
}

# Operations ``act`` has that no HTTP route corresponds to; naming one here keeps the "every operation is on a route" check honest.
# ``record_view`` and ``drop_view`` have the memory page's two view writes since 4e.  ``report_missed`` (11-28) has no page: 「这事怎么没告诉我」
# is said in a conversation, and the rows are read by ``scripts.missed_reports``.
KERNEL_ONLY_OPERATIONS: frozenset[str] = frozenset({"report_missed"})


def operations_of(entry: dict) -> tuple[str, ...]:
    value = entry.get("operation", ())
    return (value,) if isinstance(value, str) else tuple(value)
