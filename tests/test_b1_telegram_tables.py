"""B1: Markdown tables go to Telegram as one block of lines per row (tables_for_telegram)."""
import asyncio
import json

import httpx
import pytest
from app.agent_telegram import split_for_telegram, tables_for_telegram
from scripts import run_telegram_bridge as bridge

# The real five-company answer of 2026-11-15 as the bridge received it (after chat_text): the text above the
# table, the table, and the text below it.  F1_BLOCKS is what the table becomes; nothing else may change.
F1_HEAD = """\
## 结论

五家公司里，**亚马逊和英伟达的最新一季营收增长最快**，亚马逊的净利润同比增幅最大。但微软和苹果只拿到了**全年数据**，不是最新一季，所以无法和其他三家按同一期间直接比较。

## 对比表（单位：亿美元）

"""
F1_TABLE = """\
| 公司 | 最新可核验期 | 营收 | 营收同比 | 净利润 | 净利润同比 | 净利率 | 毛利率 |
|---|---|---|---|---|---|---|---|
| 微软 MSFT | FY2026 全年（截至 2026-06-30） | 3,318.39 | +17.79% | 1,337.49 | 本轮未计算 | 40.31% | 未计算 |
| 苹果 AAPL | FY2026 全年（截至 2026-09-26） | 4,788.34 | +15.06% | 1,321.75 | 本轮未计算 | 27.60% | 未计算 |
| 英伟达 NVDA | FY2027 Q2（3 个月，截至 2026-07-26） | 962.21 | +105.85% | 本轮未取到 | — | — | 74.98% |
| 特斯拉 TSLA | FY2026 Q3（3 个月，截至 2026-09-30） | 280.46 | -0.17% | 本轮未取到 | — | — | 19.59% |
| 亚马逊 AMZN | FY2026 Q2（3 个月，截至 2026-06-30） | 2,006.06 | 本轮未计算 | 626.47 | +244.90% | 31.23% | — |"""
F1_BLOCKS = """\
*微软 MSFT*
最新可核验期：FY2026 全年（截至 2026-06-30）
营收：3,318.39
营收同比：+17.79%
净利润：1,337.49
净利润同比：本轮未计算
净利率：40.31%
毛利率：未计算

*苹果 AAPL*
最新可核验期：FY2026 全年（截至 2026-09-26）
营收：4,788.34
营收同比：+15.06%
净利润：1,321.75
净利润同比：本轮未计算
净利率：27.60%
毛利率：未计算

*英伟达 NVDA*
最新可核验期：FY2027 Q2（3 个月，截至 2026-07-26）
营收：962.21
营收同比：+105.85%
净利润：本轮未取到
净利润同比：—
净利率：—
毛利率：74.98%

*特斯拉 TSLA*
最新可核验期：FY2026 Q3（3 个月，截至 2026-09-30）
营收：280.46
营收同比：-0.17%
净利润：本轮未取到
净利润同比：—
净利率：—
毛利率：19.59%

*亚马逊 AMZN*
最新可核验期：FY2026 Q2（3 个月，截至 2026-06-30）
营收：2,006.06
营收同比：本轮未计算
净利润：626.47
净利润同比：+244.90%
净利率：31.23%
毛利率：—"""
F1_TAIL = """\


## 要点

- **营收**：英伟达本季营收 962.21 亿美元，上年同期为 467.43 亿美元，同比增长最快。特斯拉营收 280.46 亿美元，上年同期为 280.95 亿美元，基本持平。亚马逊营收 2,006.06 亿美元，上年同期为 1,677.02 亿美元，但同比增幅这次没有算出来。
- **盈利**：亚马逊本季净利润 626.47 亿美元，上年同期为 181.64 亿美元，增幅远超其他公司。但这笔利润被非经营性收益明显放大，前面几轮的分析已经说明这一点。
- **毛利率**：英伟达 74.98%，特斯拉 19.59%，两家的差距很大。其他公司本轮没有可比的毛利率数据。
- **微软和苹果**：两家都只取到全年数据，净利润上年数字分别为 1,018.32 亿美元 和 1,120.10 亿美元，但同比增幅没有计算。

## 缺口

- **最新一季不统一**：微软和苹果是全年口径，其余三家是单季口径，不能直接比较。
- **英伟达和特斯拉的净利润本轮未取到**，所以这两家的盈利只能看毛利率，不能看净利润。
- **亚马逊营收同比未计算**，计算没有通过校验。
- 微软和苹果的最新季度数字，本轮没有重新取回，不能沿用前面对话里的数字。

（另有 1 处表述未能与来源核对，已保留并标注“证据不足”。）"""
F1_IN = F1_HEAD + F1_TABLE + F1_TAIL
F1_OUT = F1_HEAD + F1_BLOCKS + F1_TAIL
WIDE = "| 公司 | 期间 | 营收 | 同比 |\n|---|---|---|---|\n"
ROW = "| 甲 | FY2026 | 1.0 | +1% |"
BLOCK = "*甲*\n期间：FY2026\n营收：1.0\n同比：+1%"


def test_t01_real_answer_converts_word_for_word():
    assert (len(F1_IN), len(F1_OUT)) == (1228, 1229)          # the fixture was copied whole
    assert tables_for_telegram(F1_IN) == F1_OUT
    assert F1_BLOCKS.count("\n\n") == 4 and F1_BLOCKS.startswith("*微软 MSFT*\n最新可核验期：FY2026 全年（截至 2026-06-30）\n")
    assert "净利润：本轮未取到\n净利润同比：—\n净利率：—\n毛利率：74.98%" in F1_BLOCKS


def test_t02_broken_separator_cell_changes_nothing():
    broken = F1_IN.replace("|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|—|")
    assert broken != F1_IN and tables_for_telegram(broken) == F1_OUT
    for rule in ("|—|—|—|—|", "| – | –– | --- | :-: |", "|---|---|---|---"):
        assert tables_for_telegram(WIDE.replace("|---|---|---|---|", rule) + ROW) == BLOCK


def test_t03_narrow_table_stays_as_written():
    narrow = "| 季度 | 营收 | 同比 |\n|---|---|---|\n| Q1 | 10.2 | +5% |\n| Q2 | 11.3 | +8% |"
    assert tables_for_telegram(narrow) == narrow
    two = "| 指标 | 数值 |\n|---|---|\n| 营收 | 962.21 亿美元 |"
    assert tables_for_telegram(two) == two
    # Three columns, but a row 34 wide: converted.
    assert tables_for_telegram("| 公司 | 营收 | 营收同比 |\n|---|---|---|\n| 微软 MSFT | 3,318.39 | +17.79% |") == \
        "*微软 MSFT*\n营收：3,318.39\n营收同比：+17.79%"
    # Four columns are converted however short the rows are.
    assert tables_for_telegram("| a | b | c | d |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |") == "*1*\nb：2\nc：3\nd：4"


def test_t04_bold_markers_in_header_title_and_value():
    text = "| **公司** | **期间** | **营收** | 同比 |\n|---|---|---|---|\n| **甲** | FY2026 | **1.0** | +1% |"
    assert tables_for_telegram(text) == "*甲*\n期间：FY2026\n营收：**1.0**\n同比：+1%"


def test_t05_only_an_empty_cell_has_no_line():
    text = WIDE + "| 甲 |  | — | 本轮未取到 |\n| 乙 | – | 未计算 | |\n| 丙 | - | 本轮未计算 | N/A |"
    assert tables_for_telegram(text) == ("*甲*\n营收：—\n同比：本轮未取到\n\n*乙*\n期间：–\n营收：未计算\n\n"
                                         "*丙*\n期间：-\n营收：本轮未计算\n同比：N/A")


def test_t06_short_row_is_padded():
    assert tables_for_telegram(WIDE + "| 甲 | FY2026 | 1.0 |") == "*甲*\n期间：FY2026\n营收：1.0"


def test_t07_row_longer_than_header_keeps_the_whole_table():
    text = WIDE + "| 甲 | FY2026 | 1.0 | +1% | 多一格 |\n| 乙 | FY2026 | 2.0 | +2% |"
    assert tables_for_telegram(text) == text


def test_t08_escaped_pipe_stays_in_its_cell():
    assert tables_for_telegram(WIDE + "| 甲 | FY2026 | 1.0 \\| 2.0 | +1% |") == "*甲*\n期间：FY2026\n营收：1.0 | 2.0\n同比：+1%"


def test_t09_rows_without_a_closing_pipe():
    assert tables_for_telegram("| 公司 | 期间 | 营收 | 同比\n|---|---|---|---\n| 甲 | FY2026 | 1.0 | +1%") == BLOCK


def test_t10_separator_with_another_number_of_cells():
    assert tables_for_telegram("| 公司 | 期间 | 营收 | 同比 |\n|:--|--:|\n" + ROW) == BLOCK


def test_t11_no_separator_or_no_rows_is_left_alone():
    for text in ("| 公司 | 期间 | 营收 | 同比 |\n" + ROW, WIDE.rstrip("\n"), WIDE + "\n" + ROW,
                 "| 只有一格 |\n|---|\n| 甲 |", "公司 | 期间 | 营收 | 同比\n---|---|---|---\n甲 | FY2026 | 1.0 | +1%"):
        assert tables_for_telegram(text) == text


def test_t12_tables_inside_code_fences_are_left_alone():
    for text in ("```\n" + WIDE + ROW + "\n```", "~~~text\n" + WIDE + ROW + "\n~~~", "  ```\n" + WIDE + ROW + "\n  ```",
                 "```\n没有闭合的围栏\n\n" + WIDE + ROW):
        assert tables_for_telegram(text) == text
    # The table after a closed fence is converted.
    assert tables_for_telegram("```\n| a | b |\n```\n\n" + WIDE + ROW) == "```\n| a | b |\n```\n\n" + BLOCK


def test_t13_title_with_a_markdown_character_is_not_bolded():
    assert tables_for_telegram(WIDE + "| BRK_B | FY2026 | 1.0 | +1% |") == "BRK_B\n期间：FY2026\n营收：1.0\n同比：+1%"
    assert tables_for_telegram(WIDE + "| **甲** 集团 * | FY2026 | 1.0 | +1% |") == "**甲** 集团 *\n期间：FY2026\n营收：1.0\n同比：+1%"
    assert tables_for_telegram(WIDE + "| 甲\\ | FY2026 | 1.0 | +1% |") == "甲\\\n期间：FY2026\n营收：1.0\n同比：+1%"


def test_t14_markdown_characters_in_a_column_name_are_escaped():
    text = "| 公司 | 期间 | 营收* | P_E |\n|---|---|---|---|\n| 甲 | FY2026 | 1.0 | 20 |"
    assert tables_for_telegram(text) == "*甲*\n期间：FY2026\n营收\\*：1.0\nP\\_E：20"


def test_t15_empty_and_repeated_column_names():
    text = "| 公司 | 营收 | 营收 |  |\n|---|---|---|---|\n| 甲 | 1.0 | 2.0 | 备注文字 |"
    assert tables_for_telegram(text) == "*甲*\n营收：1.0\n营收：2.0\n备注文字"


def test_t16_empty_first_cell_gives_a_block_without_title():
    assert tables_for_telegram(WIDE + "|  | FY2026 | 1.0 | +1% |") == "期间：FY2026\n营收：1.0\n同比：+1%"
    # A row with nothing in it gives no block; a table with nothing in any row stays as written.
    assert tables_for_telegram(WIDE + ROW + "\n|  |  |  |  |") == BLOCK
    assert tables_for_telegram(WIDE + "|  |  |  |  |") == WIDE + "|  |  |  |  |"


def test_t17_citation_markers_are_not_this_functions_job():
    assert tables_for_telegram(WIDE + "| 甲 | FY2026 | 1.0 [3] | +1% [4] |") == "*甲*\n期间：FY2026\n营收：1.0 [3]\n同比：+1% [4]"


def test_t18_indented_table():
    assert tables_for_telegram("  | 公司 | 期间 | 营收 | 同比 |\n  |---|---|---|---|\n  " + ROW) == BLOCK


def test_t19_blank_lines_around_the_blocks():
    assert tables_for_telegram("前文。\n" + WIDE + ROW + "\n后文。") == "前文。\n\n" + BLOCK + "\n\n后文。"
    assert tables_for_telegram("前文。\n\n" + WIDE + ROW + "\n\n后文。") == "前文。\n\n" + BLOCK + "\n\n后文。"
    assert tables_for_telegram(WIDE + ROW + "\n") == BLOCK + "\n"


def test_t20_each_table_is_decided_alone():
    bad = WIDE + "| 甲 | FY2026 | 1.0 | +1% | 多 |"
    narrow = "| 季度 | 营收 |\n|---|---|\n| Q1 | 10.2 |"
    text = f"一\n\n{WIDE}{ROW}\n\n二\n\n{bad}\n\n三\n\n{narrow}\n\n四\n\n{WIDE}{ROW}"
    assert tables_for_telegram(text) == f"一\n\n{BLOCK}\n\n二\n\n{bad}\n\n三\n\n{narrow}\n\n四\n\n{BLOCK}"


def test_t21_text_without_a_table_comes_back_unchanged():
    for text in ("", "好", "甲\n\n\n乙  \n", "a | b | c", "|", "| 一行带竖线的话 |", F1_HEAD, F1_TAIL, "行尾\r\n两行\r\n"):
        assert tables_for_telegram(text) == text


def test_t22_converting_twice_changes_nothing_more():
    assert tables_for_telegram(F1_OUT) == F1_OUT


# --- through the bridge ---------------------------------------------------------------------------------
TOKEN = "123456789:AAH" + "x" * 32


class Telegram:
    def __init__(self):
        self.replies = []

    def record_reply(self, *args):
        self.replies.append(args)


class Client:
    """Answers one turn with ``answer`` and records what is sent; ``statuses`` are Telegram's replies in order."""

    def __init__(self, answer, statuses=()):
        self.answer, self.statuses, self.posts = answer, list(statuses), []

    async def post(self, url, json):
        self.posts.append(dict(json))
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, json={"ok": status == 200, "result": {"message_id": len(self.posts)}})

    def stream(self, method, url, **kwargs):
        client = self

        class Response:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def aiter_bytes(self):
                data = json.dumps({"text": client.answer}, ensure_ascii=False)
                yield f"event: delta\ndata: {data}\n\n".encode()

        return Response()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    monkeypatch.delenv("FINBOT_TG_TABLE_CARDS", raising=False)
    monkeypatch.delenv("FINBOT_FP12_TG_SPLIT", raising=False)


def _turn(client, telegram, **more):
    return asyncio.run(bridge._bot_turn(client, "cred", "owner", 4242, {}, telegram, "bot", "助理", "问", **more))


def test_t23_bridge_sends_the_blocks_by_default(token):
    client, telegram = Client(F1_IN), Telegram()
    _turn(client, telegram)
    assert [post["text"] for post in client.posts] == ["【助理】\n" + F1_OUT]
    assert client.posts[0]["parse_mode"] == "Markdown"
    assert [reply[2] for reply in telegram.replies] == ["【助理】\n" + F1_OUT]     # what was sent is what is remembered


def test_t24_switch_off_sends_todays_text(token, monkeypatch):
    monkeypatch.setenv("FINBOT_TG_TABLE_CARDS", "off")
    client = Client(F1_IN)
    _turn(client, Telegram())
    assert [post["text"] for post in client.posts] == ["【助理】\n" + F1_IN]


def test_t25_citation_markers_are_gone_before_the_table_is_read(token):
    client = Client("结论 [1]。\n\n" + WIDE + "| 甲 [2] | FY2026 | 1.0 [3] | +1% [4][5] |\n\n来源：\n[1] 某文件")
    _turn(client, Telegram())
    assert client.posts[0]["text"] == "【助理】\n结论。\n\n" + BLOCK


def test_t26_a_failing_conversion_still_sends_the_answer(token, monkeypatch, capsys):
    monkeypatch.setattr(bridge, "tables_for_telegram", lambda text: 1 / 0)
    client = Client(WIDE + ROW)
    _turn(client, Telegram())
    assert client.posts[0]["text"] == "【助理】\n" + WIDE + ROW
    assert "table conversion failed" in capsys.readouterr().err


def test_t27_a_long_table_is_split_between_blocks(token):
    row = "| 公司{n:03d} | FY2026 Q3（3 个月，截至 2026-09-30） | 2,006.06 | +17.79% | 626.47 | 本轮未计算 | 31.23% | — |"
    table = F1_TABLE.split("\n")[0] + "\n|---|---|---|---|---|---|---|---|\n" + "\n".join(row.format(n=n) for n in range(60))
    client, telegram = Client("## 对比表\n\n" + table + "\n\n## 缺口\n\n- 没有。"), Telegram()
    _turn(client, telegram)
    texts = [post["text"] for post in client.posts]
    assert len(texts) == 2 and all(len(text) <= 3800 for text in texts)
    blocks = [block for text in texts for block in text.split("\n\n") if block.startswith("*公司")]
    assert len(blocks) == 60 and all(block.count("\n") == 7 and block.endswith("毛利率：—") for block in blocks)
    assert texts == split_for_telegram("【助理】\n" + tables_for_telegram(client.answer), 3800)


def test_t28_plain_text_fallback_shows_the_same_words(token):
    text = "| 公司 | 期间 | 营收* | P_E |\n|---|---|---|---|\n| 甲 | FY2026 | 1.0 | 20 |"
    client = Client(text, statuses=[400, 200])
    _turn(client, Telegram())
    first, second = client.posts
    assert first["parse_mode"] == "Markdown" and first["text"] == "【助理】\n*甲*\n期间：FY2026\n营收\\*：1.0\nP\\_E：20"
    assert "parse_mode" not in second and second["text"] == "【助理】\n*甲*\n期间：FY2026\n营收*：1.0\nP_E：20"
