"""Builds ruler/suites/baseline-v1.json.  Figures are in 亿美元 (1e8 USD), read from the shadow database on 2026-11-23
(backup finbot-20261123-073322.dump).  Each number gets the spellings an answer may reasonably use."""
import json, math, sys

def num(v):
    """Alternatives for a figure given in 亿: 亿 (1158.44 / 1158.4), billions (115.84 / 115.8), millions (115844)."""
    out = []
    def add(x, places):
        for s in (f"{x:.{places}f}", f"{math.floor(x * 10**places) / 10**places:.{places}f}"):
            if s not in out: out.append(s)
    add(v, 2); add(v / 10, 2)
    if abs(v) >= 100: add(v, 1); add(v / 10, 1)
    m = f"{v * 100:.0f}"
    if len(m.lstrip('-')) >= 3 and m not in out: out.append(m)
    return out

def pct(p):
    out = []
    for s in (f"{p:.2f}", f"{math.floor(p * 100) / 100:.2f}", f"{p:.1f}", f"{math.floor(p * 10) / 10:.1f}"):
        if s not in out: out.append(s)
    return out

def turn(text, *groups, exclude=(), status=None):
    checks = {"status": status} if status else {}
    if groups: checks["include_any"] = [list(g) for g in groups]
    if exclude: checks["exclude"] = list(exclude)
    return {"text": text, "checks": checks}

def case(cid, kind, title, *turns):
    return {"id": cid, "kind": kind, "title": title, "turns": list(turns)}

NVDA, AAPL, MSFT = ["英伟达", "nvda", "nvidia"], ["苹果", "aapl", "apple"], ["微软", "msft", "microsoft"]
AMD, TSLA, INTC = ["amd", "超威"], ["特斯拉", "tsla", "tesla"], ["英特尔", "intc", "intel"]
GOOGL, AMZN, META, MU = ["谷歌", "googl", "alphabet"], ["亚马逊", "amzn", "amazon"], ["meta"], ["美光", "micron"]

cases = [
 # --- 简单事实 ---
 case("F01", "fact", "英伟达最近一季营收", turn("英伟达最近一个季度的营收是多少？", num(1158.44))),
 case("F02", "fact", "英伟达最近一季毛利率", turn("英伟达最近一个季度的毛利率是多少？", pct(74.82))),
 case("F03", "fact", "苹果最近财年营收", turn("苹果最近一个财年的营收是多少？", num(4788.34))),
 case("F04", "fact", "苹果最近财年净利润", turn("苹果最近一个财年的净利润是多少？", num(1321.75))),
 case("F05", "fact", "微软 FY2026 营收", turn("微软 2026 财年全年的营业收入是多少？", num(3318.39))),
 case("F06", "fact", "微软 FY2026 净利润", turn("微软 2026 财年的净利润是多少？", num(1337.49))),
 case("F07", "fact", "AMD 最近一季营收", turn("AMD 最近一个季度的营收是多少？", num(133.77))),
 case("F08", "fact", "特斯拉最近一季毛利率", turn("特斯拉最近一个季度的毛利率是多少？", pct(19.59))),
 case("F09", "fact", "英特尔最近一季净利润", turn("英特尔最近一个季度的净利润是多少？", num(33.20))),
 case("F10", "fact", "谷歌最近一季营业利润", turn("谷歌最近一个季度的营业利润是多少？", num(405.76))),
 case("F11", "fact", "亚马逊 FY2025 营收", turn("亚马逊 2025 财年的营收是多少？", num(7169.24))),
 case("F12", "fact", "Meta FY2025 净利润", turn("Meta 2025 财年的净利润是多少？", num(604.58))),
 case("F13", "fact", "美光最近财年营收", turn("美光最近一个财年的营收是多少？", num(1331.88))),
 case("F14", "fact", "苹果股票代码", turn("苹果的股票代码是什么？", ["aapl"])),
 case("F15", "fact", "英伟达最近一季经营现金流", turn("英伟达最近一个季度的经营现金流是多少？", num(482.53))),
 # --- 财报简述 ---
 case("B01", "brief", "英伟达最新财报", turn("英伟达最新财报简单说说", NVDA, ["q3", "第三季", "三季度"], num(1158.44))),
 case("B02", "brief", "AMD 最新财报", turn("帮我看下 AMD 最新的财报的简介", AMD, ["q3", "第三季", "三季度"], num(133.77))),
 case("B03", "brief", "苹果最新财报", turn("帮我看下苹果最新财报的简介", AAPL, ["2026"], num(4788.34) + num(1144.77))),
 case("B04", "brief", "特斯拉最近一季", turn("特斯拉最近一季财报怎么样？", TSLA, num(280.46))),
 case("B05", "brief", "英特尔最近一季", turn("英特尔最近一季财报的主要数字过一遍", INTC, num(165.13))),
 case("B06", "brief", "谷歌最近一季", turn("谷歌最近一个季度业绩怎么样？", GOOGL, num(1275.77))),
 case("B07", "brief", "美光最近财年", turn("美光最近一个财年的主要财务数据过一遍", MU, num(1331.88))),
 case("B08", "brief", "微软 FY2026", turn("微软 2026 财年的主要财务数据过一遍", MSFT, num(3318.39), num(1337.49))),
 case("B09", "brief", "英伟达亮点与隐忧", turn("帮我把 NVDA 最近一季的业绩亮点和隐忧各列 3 条", NVDA, ["亮点"], ["隐忧", "风险", "担忧"])),
 case("B10", "brief", "亚马逊 FY2025", turn("亚马逊 2025 财年主要财务数据过一遍", AMZN, num(7169.24), num(776.70))),
 # --- 多公司比较 ---
 case("C01", "compare", "英伟达对 AMD 营收", turn("英伟达和 AMD 最近一个季度的营收各是多少，谁更高？", num(1158.44), num(133.77))),
 case("C02", "compare", "苹果对微软净利润", turn("苹果最近一个财年和微软 2026 财年的净利润对比一下", num(1321.75), num(1337.49))),
 case("C03", "compare", "英伟达对 AMD 毛利率", turn("英伟达和 AMD 最近一季的毛利率各是多少，差几个点？", pct(74.82), pct(53.90))),
 case("C04", "compare", "特斯拉对英特尔营业利润", turn("特斯拉和英特尔最近一季谁的营业利润更高？各是多少", num(7.18), num(25.22))),
 case("C05", "compare", "苹果两个财年营收", turn("苹果 2026 财年和 2025 财年的营收各是多少，增长了多少？", num(4788.34), num(4161.61), pct(15.06))),
 case("C06", "compare", "微软两个财年净利润", turn("微软 2026 财年和 2025 财年的净利润各是多少，差多少？", num(1337.49), num(1018.32), num(319.17))),
 case("C07", "compare", "三家芯片公司营收", turn("把英伟达、AMD、英特尔最近一个季度的营收列个表", num(1158.44), num(133.77), num(165.13))),
 case("C08", "compare", "亚马逊对 Meta 营业利润", turn("亚马逊和 Meta 2025 财年的营业利润谁高？各是多少", num(799.75), num(832.76))),
 case("C09", "compare", "美光两个财年营收", turn("美光最近一个财年的营收比上一财年增长了多少？两年各是多少", num(1331.88), num(373.78))),
 case("C10", "compare", "英特尔同比", turn("英特尔最近一季的营收和去年同期各是多少？", num(165.13), num(136.53))),
 # --- 追问 ---
 case("U01", "followup", "营收后问环比", turn("英伟达最近一个季度的营收是多少？", num(1158.44)), turn("它环比增长了多少？", pct(20.39))),
 case("U02", "followup", "营收后问净利润", turn("苹果最近一个财年的营收是多少？", num(4788.34)), turn("净利润呢？", num(1321.75))),
 case("U03", "followup", "营收后问同比", turn("微软 2026 财年营收多少？", num(3318.39)), turn("比上一财年增长了多少？", pct(17.79))),
 case("U04", "followup", "营收后问毛利率", turn("AMD 最近一季营收多少？", num(133.77)), turn("毛利率呢？", pct(53.90))),
 case("U05", "followup", "换一家公司", turn("特斯拉最近一季的营收是多少？", num(280.46)), turn("那英特尔呢？", num(165.13))),
 case("U06", "followup", "营业利润后问利润率", turn("谷歌最近一季的营业利润是多少？", num(405.76)), turn("营业利润率是多少？", pct(31.81))),
 case("U07", "followup", "净利润后问去年同期", turn("英特尔最近一季净利润多少？", num(33.20)), turn("去年同期呢？", num(40.63))),
 case("U08", "followup", "营收后问毛利率（财年）", turn("美光最近一个财年的营收是多少？", num(1331.88)), turn("毛利率多少？", pct(80.72))),
 case("U09", "followup", "净利润后问净利率", turn("英伟达最近一季的净利润是多少？", num(652.87)), turn("净利率是多少？", pct(56.36))),
 case("U10", "followup", "营收后问营业利润率", turn("亚马逊 2025 财年营收多少？", num(7169.24)), turn("营业利润率多少？", ["11.16", "11.15", "11.2", "11.1"])),
 # --- 回忆细节（细节是编的，不是 owner 的真实信息） ---
 case("R01", "recall", "警戒线", turn("先记一下：我给英伟达设的毛利率警戒线是 68%，低于这个我就减仓。", status="any"), turn("苹果的股票代码是什么？", ["aapl"]), turn("我刚才给英伟达设的毛利率警戒线是多少？", ["68"])),
 case("R02", "recall", "买入条件", turn("我打算等特斯拉毛利率回到 22% 再考虑买。", status="any"), turn("什么是市盈率？简单说"), turn("我说特斯拉毛利率要回到多少才考虑买？", ["22"])),
 case("R03", "recall", "代号", turn("我关注 AMD 是因为它的数据中心业务，这条理由我记作「蓝鲸计划」。", status="any"), turn("英伟达的股票代码是什么？", ["nvda"]), turn("我给 AMD 那条理由起的代号是什么？", ["蓝鲸"])),
 case("R04", "recall", "人名", turn("我下周三要和同事老周开会讨论英特尔。", status="any"), turn("什么是营收？"), turn("我下周要和谁讨论英特尔？", ["老周"])),
 case("R05", "recall", "它自己答过的数", turn("英伟达最近一个季度的营收是多少？", num(1158.44)), turn("什么是毛利率？"), turn("你刚才告诉我的英伟达营收是多少？", num(1158.44))),
 case("R06", "recall", "单位偏好", turn("我的习惯：以后给我报数字都用亿美元做单位。", status="any"), turn("AMD 的股票代码是什么？", ["amd"]), turn("我刚才让你报数字用什么单位？", ["亿美元"])),
 case("R07", "recall", "目标线", turn("记一下：微软我只看 Azure 增速，目标线是 30%。", status="any"), turn("10-K 和 10-Q 有什么区别？"), turn("微软那条我的目标线是多少？", ["30"])),
 case("R08", "recall", "回到最开始", turn("苹果最近一个财年的净利润是多少？", num(1321.75)), turn("英伟达的股票代码是什么？", ["nvda"]), turn("回到最开始，苹果那个净利润是多少来着？", num(1321.75))),
 # --- 不查资料 ---
 case("G01", "general", "自我介绍", turn("你好，请用一句话介绍你自己。")),
 case("G02", "general", "什么是营收", turn("什么是营收？", ["收入"])),
 case("G03", "general", "什么是市盈率", turn("什么是市盈率？简单说", ["股价", "价格"], ["盈利", "收益", "利润"])),
 case("G04", "general", "鹰派鸽派", turn("鹰派和鸽派代表什么含义？", ["加息", "紧缩", "收紧"], ["降息", "宽松"])),
 case("G05", "general", "毛利率与净利率", turn("毛利率和净利率有什么区别？", ["成本"], ["净利"])),
 case("G06", "general", "10-K 与 10-Q", turn("10-K 和 10-Q 有什么区别？", ["年"], ["季"])),
 case("G07", "general", "冒泡排序", turn("给我写一个冒泡排序", ["for "])),
]
json.dump({"version": 1, "cases": cases}, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
