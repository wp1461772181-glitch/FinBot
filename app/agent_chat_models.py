import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid, func, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class AgentFAQ(Base):
    __tablename__ = "agent_faq"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)

class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Archiving is a logical delete: the conversation and its messages stay, it just stops being
    # listed.  NULL means not archived.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The bot whose line this is (agent_bots).  NULL: a guest's conversation, or an owner's from before bots;
    # the owner's are moved under the default bot when it is created.
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    # Where the conversation came from when it was not him: "ruler" (the evaluation harness).  The monthly memory review and the message
    # counts leave such conversations out: test questions are not his habits (11-28: 「你偏好用表格」 was learned from repeated test runs).
    origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="complete")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentConversationTitle(Base):
    """A name the owner gave a conversation.  Without a row the first question names it; a separate
    table keeps the conversation table unchanged (it is created with the others at startup)."""
    __tablename__ = "agent_conversation_titles"
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_conversations.id", ondelete="CASCADE"), primary_key=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentConversationSummary(Base):
    """One segment of the oldest layer of a conversation's context: a summary of the turns whose
    messages lie between ``from_sequence`` and ``upto_sequence``.  Segments are only appended and
    never rewritten, so a fact passes through at most one lossy compression."""
    __tablename__ = "agent_conversation_summaries"
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_agent_summary_conversation_seq"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    from_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    upto_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The turns this segment covers, by id (whole turns: turns that ran together overlap in their row numbers, so a range of rows is not a set of
    # turns).  None for a segment made before: it covers the turns whose first row lies up to ``upto_sequence``.
    turn_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AgentResearchQueue(Base):
    """The research queue (the stocks the owner follows) as the site owner keeps it, one row per owner
    credential hash, so that clearing the browser does not clear it.  A guest's queue stays in their
    browser.  A separate table keeps the existing ones unchanged (it is created with them at startup)."""
    __tablename__ = "agent_research_queue"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)



class AgentProfileItem(Base):
    """One line of the owner's profile: a lasting preference, something about the owner, or a standing
    instruction.  Every row quotes the owner's own words (``quote``); text from pages, filings or tool
    results never becomes a row.  Rows are archived rather than deleted when a newer one replaces them;
    only the owner deleting a row on the memory page removes it."""
    __tablename__ = "agent_profile_items"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # A short slug (currency_unit, answer_language): a newer item of the same kind and topic replaces
    # the older one.  NULL: the item replaces nothing.
    topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    quote: Mapped[str] = mapped_column(String(200), nullable=False)
    # The layer (second edition): NULL is global, read by every bot; a bot id is that bot's own memory, read
    # by it and by the default bot.  Added to older tables by ``agent_profile.ensure_bot_column``.
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The monthly review's proposals (origin ``pattern``, status ``proposed``): his own sentences as examples
    # ([{message_id, quote, date}]) and the run that made it.  Added to older tables by ``agent_profile.ensure_review_columns``.
    examples: Mapped[list | None] = mapped_column(JSON, nullable=True)
    review_run: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Stage 4c: when the owner's own words last bore the item out (not use: ``last_used_at`` is that), when the quarterly settle archived it and
    # why, and when it became long-term.  Added to older tables by ``agent_profile.ensure_seen_columns`` (which also backfills last_seen_at).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the owner confirmed a monthly-review guess (origin ``pattern``); the settle's 60-day rule counts from it, not from ``updated_at``.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stage 4f: the role template he chose that wrote this line (a label only; nothing reads it to decide anything).  Added to older tables by
    # ``agent_profile.ensure_template_column``.
    template: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AgentConversationRecall(Base):
    """The owner's index of past conversations, read by ``recall_conversations`` and the memory page.
    Row ``seq`` 0 holds the owner's own questions; rows 1.. mirror the summary segments.  Every row
    carries the conversation's name.  It is memory, not evidence: nothing here is ever numbered or cited.
    Derived from the conversation tables, so ``agent_recall.backfill`` can rebuild it."""
    __tablename__ = "agent_conversation_recall"
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_conversations.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentTask(Base):
    """A scheduled job of the owner (agent_tasks).  ``kind`` brief: the agent answers ``instruction``
    unattended (read tools only) and the answer goes to the inbox; kind alerts: no model, the runner checks
    new filings, news leads and price lines (``config``) for the scope.  Schedule math is in agent_tasks."""
    __tablename__ = "agent_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="brief")
    schedule_kind: Mapped[str] = mapped_column(String(12), nullable=False)      # daily | weekdays | hourly | every
    schedule_time: Mapped[str] = mapped_column(String(5), nullable=False)       # HH:MM (hourly: only MM counts; every: the first time of day)
    every_value: Mapped[int | None] = mapped_column(Integer, nullable=True)     # every: the interval's size, in every_unit
    every_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)    # hours | days | weeks
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)        # at most this many runs; NULL: no limit
    runs_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # runs that reached the model
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)     # Phase 5
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="research_queue")  # research_queue | symbols
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    channel: Mapped[str] = mapped_column(String(12), nullable=False, default="inbox")         # inbox | telegram
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # The bot the task belongs to (second edition, stage C): its settings and memory run the task and its
    # results are posted in that bot's line.  NULL only on a table from before bots, until the default bot
    # adopts it (agent_bots.ensure_default_bot).  Added to older tables by ``agent_tasks.ensure_bot_columns``.
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentTaskRun(Base):
    """One run of a task (the bot page lists a bot's latest 20).  ``posted``: the run's conclusion went into
    the bot's line; a quiet run (nothing new) or a failed one posts nothing."""
    __tablename__ = "agent_task_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    task_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    posted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class AgentInboxItem(Base):
    """One entry of the owner's inbox.  Section brief (简报): a task's answer or an alert, each with its
    numbered ``sources``; section confirm (待你确认): a write an unattended run suggested.  A suggestion holds
    the validated operation and no capability: the owner mints the card from the inbox and presses it."""
    __tablename__ = "agent_inbox_items"
    __table_args__ = (UniqueConstraint("owner_hash", "dedupe_key", name="uq_agent_inbox_dedupe"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    section: Mapped[str] = mapped_column(String(10), nullable=False)              # brief | confirm
    kind: Mapped[str] = mapped_column(String(16), nullable=False)                 # task_brief | filing | news | price | action
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="unread")  # unread | read | done | dismissed
    # The bot whose task made the entry (stage C).  A brief is posted in that bot's line and this row is its
    # unread mark; a 待你确认 entry is labelled with the bot.  NULL: from before bots, the default bot's.
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class AgentBackgroundModel(Base):
    """The model the owner's scheduled tasks use.  A chat key lives only in one request's memory, so
    tasks need their own: encrypted with secret_box, never returned, revocable (``ciphertext`` NULL)."""
    __tablename__ = "agent_background_model"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentBot(Base):
    """One of the owner's bots (personal agent plan, second edition): a long-lived post with one ongoing
    conversation.  ``description`` is its work instruction.  ``focus`` narrows attention, never data:
    ``{"companies": [{"symbol", "name"}], "theme": str|None}``; exactly one company makes it the default
    company of unnamed questions.  ``tool_scope`` NULL means every tool; a list can only remove tools.
    ``model`` names a model catalog entry (agent_model_catalog); NULL uses the catalog's default."""
    __tablename__ = "agent_bots"
    __table_args__ = (UniqueConstraint("owner_hash", "name", name="uq_agent_bots_owner_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    focus: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The bot's reasoning effort (a provider tier, agent_chat_provider.REASONING_EFFORTS); NULL: the environment default.
    # Added to older tables by ``agent_bots.ensure_columns``.
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Which turn engine this bot runs: NULL the existing turn, "v2" the kernel (app/kernel).  Added to older tables by ``agent_bots.ensure_columns``.
    engine: Mapped[str | None] = mapped_column(String(16), nullable=True)
    avatar: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # The bloub look the owner picked, ``{"shape", "color"}`` (an older ``expression`` key is ignored); NULL: never customised (the frontend
    # derives a default from the bot id).  Added to older tables by ``agent_bots.ensure_columns``.
    avatar_look: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    group_name: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    template: Mapped[str] = mapped_column(String(20), nullable=False, default="blank")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    daily_notify_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Its usual skills (agent_skills ids, listed first and offered first after 「/」); NULL: none.  Added to
    # older tables by ``agent_skills.ensure_columns``.
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentModelEntry(Base):
    """A model catalog entry the owner added on the settings page (agent_model_catalog).  Entries from the
    deployment's config file are not rows.  The key is either here, encrypted with secret_box
    (``key_source`` vault), or read from the named environment variable (``key_source`` env)."""
    __tablename__ = "agent_model_catalog"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    key_source: Mapped[str] = mapped_column(String(8), nullable=False)          # vault | env
    key_env: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    migrated_from: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # The model's context window in tokens; NULL means the default (128k).  The history budget follows it.
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional prices in USD per million tokens (NULL: not set; cost needs input and output).  A call's cost is worked out
    # when its ledger row is written (model_usage), so an edit here changes only later rows.  Added to older tables by ``ensure_price_columns``.
    price_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_output: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_cache_read: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_cache_write: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentModelRole(Base):
    """Which catalog model does a job (agent_model_roles): ``earnings`` reads earnings releases, ``forecast`` is
    reserved for the forecast job.  No row means the server's default model."""
    __tablename__ = "agent_model_roles"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class XSearchUsage(Base):
    """How many posts the owner's X searches have read on one UTC day (x_search_usage); X bills by post read, so
    ``search_x`` checks this against its daily cap before it asks and adds what it got afterwards."""
    __tablename__ = "x_search_usage"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    posts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AgentPushoverConfig(Base):
    """The owner's Pushover user key and app token (Task 12), each encrypted with secret_box and never
    returned by any endpoint; the decrypted pair only goes into the sentinel's snapshot file (0600)."""
    __tablename__ = "agent_pushover_config"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_key_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    app_token_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class AgentTelegramBind(Base):
    """The owner's Telegram bridge binding.  The bot token is encrypted with secret_box, never
    returned by any endpoint.  The one-time bind code lives here (hash of a random short code)
    and is cleared after confirmation.  ``chat_id`` and ``user_id`` are the bound Telegram
    account; the bridge ignores messages from any other sender."""
    __tablename__ = "agent_telegram_bind"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_token_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Telegram ids pass 2**31 (BIGINT; older tables are widened by agent_telegram.ensure_columns).
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bind_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # UX batch 2 (P4): a bind code is good for 30 minutes (older tables get the column from ensure_columns).
    bind_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentTelegramBot(Base):
    """A bot's own Telegram bot (UX batch 2, P4).  Optional: a bot without one keeps using the shared bot of
    ``agent_telegram_bind`` (the default bot's), with 「[名字]」 in front.  The token is encrypted with secret_box
    and never returned; ``token_fingerprint`` keeps one token on one bot (two pollers of one token get 409).
    The bound chat is the owner's own, checked per Telegram bot.  ``update_offset`` survives a bridge restart."""
    __tablename__ = "agent_telegram_bots"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    token_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tg_bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bind_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bind_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    update_offset: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unbound")  # unbound | running | invalid | conflict
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentTelegramMessage(Base):
    """One message to or from the owner's Telegram chat, by bot (second edition, stage D).

    ``source`` notify (a bot called notify_telegram) and alert (an alerts task with 也发 Telegram) are queued
    here by the API or the runner and sent by the bridge, which alone holds the bot token; they count
    against the bot's daily cap.  ``source`` reply is an answer the bridge sent.  ``telegram_message_id``
    lets a reply to the message find its bot again.  The recipient is never stored per message: the
    bridge sends only to the bound chat."""
    __tablename__ = "agent_telegram_messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)          # notify | alert | reply
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # pending | sent | failed
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    inbox_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # The bot's own Telegram bot (agent_telegram_bots.id) it went through; NULL is the shared bot.  Telegram
    # message ids are per chat, so a reply is matched within one Telegram bot.
    telegram_bot_row_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stage 1e: the outbox is channel-neutral.  Added to older tables by ``agent_telegram.ensure_columns``.
    # ``channel`` telegram | wechat; the rows of one message share ``group_id`` (NULL: the row is its own group);
    # ``failure`` says why a row was closed (send_failed | expired | partial: sent, but only the first part); ``acked_at`` is when the
    # owner next wrote on that channel after the row was sent.
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="telegram", server_default="telegram")
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # A bridge stamps the rows it takes (channels.pending); the sweep leaves a row alone for CLAIM_SECONDS after.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentChannelPref(Base):
    """Where the owner wants proactive messages (agent_channel_prefs): the channels in order, and whether a message
    goes to the first available one (``first``) or to every available one (``all``).  No row: Telegram only."""
    __tablename__ = "agent_channel_prefs"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    channels: Mapped[str] = mapped_column(Text, nullable=False)   # a JSON list
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentSkill(Base):
    """A skill (agent_skills): a recipe of steps, the catalog tools it may use and an output format, never
    code.  ``owner_hash`` builtin for the seeded ones.  ``status`` draft: drafted by the model at the owner's
    request, inert (never listed or usable) until the owner saves it in the editor."""
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("owner_hash", "name", name="uq_agent_skills_owner_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)          # builtin | mine | imported
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")  # active | draft
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class RoleTemplateApplication(Base):
    """One time the owner applied a role template (stage 4f): what it created, so the page can show it and take it back.
    ``created`` is {profile_item_ids, task_ids, skill_ids, usual_added}; ``skipped`` is [{key, reason}].  Nothing here is read to decide
    how the agent behaves."""
    __tablename__ = "role_template_applications"
    __table_args__ = (Index("ix_role_template_applications_owner_applied", "owner_hash", "applied_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template: Mapped[str] = mapped_column(String(32), nullable=False)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    skipped: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class NewsItem(Base):
    """Normalized item fetched from a configured public news source (news_items)."""
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("source_id", "dedupe_key", name="uq_news_items_source_dedupe"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    time_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tickers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    keywords_hit: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="zh-CN")
    raw_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)


class NewsPushLog(Base):
    """Tracks which news_items have already been pushed per owner/channel so each item is pushed at most once."""
    __tablename__ = "news_push_log"
    __table_args__ = (UniqueConstraint("news_item_id", "owner_hash", "channel", name="uq_news_push_log_item_owner_channel"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    news_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="finbot_notify")
    inbox_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    pushed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)



class PortfolioTransaction(Base):
    """One entry of the owner's manual portfolio ledger (personal finance assistant, Task 6).  ``symbol`` is empty for
    the cash kinds; ``kind`` is opening, buy, sell, dividend, split, deposit, withdraw or cash_adjust.  Positions,
    costs and available funds are always recomputed from these rows (app.portfolio), never stored."""
    __tablename__ = "portfolio_transactions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    ratio: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PortfolioPlan(Base):
    """The owner's own plan for one position: free text plus the prices that decide when to add, stop out or take profit."""
    __tablename__ = "portfolio_plans"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), primary_key=True)
    plan_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    add_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WatchRule(Base):
    """One rule the owner set for when he wants to be told (stage 5b-1, ``app/watch_rules.py``).  The fields are structured; the plain-language
    reading is written by code from them and is not stored.  ``levels`` is a list of {threshold, level}; deleting is soft (``enabled`` false,
    ``deleted_at`` set).  ``quote`` is his own words that asked for it; ``fired_once`` is for ``repeat=once`` (kept for the sentinel bridge)."""
    __tablename__ = "watch_rules"
    __table_args__ = (Index("ix_watch_rules_owner", "owner_hash", "enabled"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    metric: Mapped[str] = mapped_column(String(24), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    levels: Mapped[list] = mapped_column(JSON, nullable=False)
    window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat: Mapped[str] = mapped_column(String(8), nullable=False, default="daily")
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_on: Mapped[date] = mapped_column(Date, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="owner")
    quote: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    fired_once: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WatchPresetOverride(Base):
    """What the owner changed on one system default rule (stage 5b-2, ``app/watch_presets.py``): switched off, or other levels.  A preset
    with no row is at its default; deleting the row is 「恢复默认」.  ``levels`` is None when only ``enabled`` was changed."""
    __tablename__ = "watch_preset_overrides"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    preset_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    levels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AlertSetting(Base):
    """The owner's sensitivity (quiet / standard / sensitive) and the 5-minute-moves switch (stage 5b-2); no row means the defaults."""
    __tablename__ = "alert_settings"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    sensitivity: Mapped[str] = mapped_column(String(12), nullable=False, default="standard")
    short_moves: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OwnerView(Base):
    """The owner's own view of one company, in his words.  One version is ``active`` per (owner, symbol); a newer one marks the old
    ``superseded``, ``drop_view`` marks it ``dropped`` and nothing is deleted by the model.  Not evidence, and it authorizes nothing."""
    __tablename__ = "owner_views"
    __table_args__ = (Index("uq_owner_views_active", "owner_hash", "symbol", unique=True, postgresql_where=sql_text("status = 'active'")),
                      Index("ix_owner_views_owner_symbol", "owner_hash", "symbol"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    quote: Mapped[str] = mapped_column(String(400), nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")      # active | superseded | dropped | archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stage 4c: why the quarterly settle archived it (status ``archived``); added to older tables by ``owner_views.ensure_archive_column``.
    archived_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ViewReview(Base):
    """Stage 4d: the quarterly look back at one version of the owner's view (``app/view_review.py``).  ``text`` is the model's judgement as
    it wrote it; ``unmatched_figures`` only names figures in it that are not in the input; ``input_snapshot`` is the code-built price and
    quarter label the page shows as the basis.  Nothing here is ever written back to the view or the profile."""
    __tablename__ = "view_reviews"
    __table_args__ = (Index("ix_view_reviews_owner_view", "owner_hash", "view_id", sql_text("created_at DESC")),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    view_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)
    text: Mapped[str] = mapped_column(String(400), nullable=False)
    unmatched_figures: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MemoryJob(Base):
    """The calendar of the memory jobs (app/memory_schedule.py): one row per (job, owner) with when it last ran and who holds it now.
    ``claimed_at``/``claimed_by`` are the lock two workers race for; a claim older than 30 minutes is dead (a restart cut it off)."""
    __tablename__ = "memory_jobs"
    job: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)     # the last run that counts (done or skipped)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)    # the last time any run ended
    last_outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)                      # done | skipped | failed
    last_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)       # after a failure: not before this
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class EarningsEvent(Base):
    """One earnings 8-K (Item 2.02) the sentinel found, and where its two messages stand.  The follow-up timer
    is ``followup_due_at``; both it and the statuses live here so a restart picks up what is unsent."""
    __tablename__ = "earnings_events"
    __table_args__ = (UniqueConstraint("owner_hash", "accession", name="uq_earnings_event_accession"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    held: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")   # received | analysing | first_sent | failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EarningsHistory(Base):
    """earnings_history: what each past release said and how the stock reacted, one row per accession.  Rows are
    written from the release's own text and prices up to the day before it, so a row never contains anything that
    was unknown at its release time; readers take only rows released before the event they analyse."""
    __tablename__ = "earnings_history"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    quarter: Mapped[str] = mapped_column(String(8), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    guidance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)     # given in this release, for the next quarter
    actual: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reaction: Mapped[float | None] = mapped_column(Float, nullable=True)           # R, first-day return (filled once known)
    sigma: Mapped[float | None] = mapped_column(Float, nullable=True)              # daily σ before the release
    verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)          # up | down | flat
    reader_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ModelCall(Base):
    """The model-call ledger (model_usage): one row per attempt of every call the app makes to a model, tagged with what it
    was for.  Never a key, a URL, a header or any text of the call: only who, what for, how long and how many tokens."""
    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_created_at", "created_at"),
                      Index("ix_model_calls_owner_created", "owner_hash", "created_at"),
                      Index("ix_model_calls_turn", "turn_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    owner_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(160), nullable=False, default="")      # the provider's model id
    catalog_name: Mapped[str | None] = mapped_column(String(40), nullable=True)      # the catalog entry, as named at call time
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    job: Mapped[str | None] = mapped_column(String(64), nullable=True)               # a background job's id or name
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)             # a short code, never text
    ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)   # the input NOT served from / written to the cache
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streamed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)   # the answer text was passed on as it arrived
    # USD, fixed when the row was written from the model's prices then; NULL: no price, or a cache price the call needs is not set.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class MemoryEvent(Base):
    """One change to what the assistant keeps about the owner (5d-2, ``app/memory_events.py``): a profile item or a version of his view of a
    company was recorded, changed, archived, restored, confirmed or deleted, by whom (``by``) and on what basis (``basis``: his quote, the
    conversation, the review's examples ...).  Append-only: written in the same transaction as the change it records.  Deleting an item removes
    its words from its earlier events too (``memory_events.scrub``); ``reconstructed`` marks the events the one-off backfill rebuilt from the
    rows' own timestamps."""
    __tablename__ = "memory_events"
    __table_args__ = (Index("ix_memory_events_owner_at", "owner_hash", sql_text("at DESC"), sql_text("id DESC")),
                      Index("ix_memory_events_owner_item", "owner_hash", "item_id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    target: Mapped[str] = mapped_column(String(8), nullable=False)               # profile | view
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)              # the profile item, or the view version
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    by: Mapped[str] = mapped_column(String(12), nullable=False)                   # chat | page | review | settle | template | extract | unknown
    text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    before: Mapped[str | None] = mapped_column(String(200), nullable=True)        # an edit's old text
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    basis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reconstructed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sql_text("false"))
