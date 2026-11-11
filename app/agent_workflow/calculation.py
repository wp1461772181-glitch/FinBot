"""Small Decimal arithmetic over inputs present in this turn's accepted sources."""
import ast
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from .semantic import _MAGNITUDE, PERIOD_TEXT, ACCESSION, SOURCE_ID, TASK_ID, figure_tokens
from .fp_flags import flag
# Percent and unit factors only: a power of ten converts a cited value (to 亿 or billions), it adds no figure.
CONSTANTS=frozenset({0,1,100,1000,10**4,10**6,10**8,10**9,10**12})


def format_price(value):
    """A stored price as the reader knows it: Yahoo's single-precision 92.06999969482422 is 92.07.  Display and
    comparison only; the stored rows (and the hashes and forecast manifests built on them) stay untouched."""
    text=format(Decimal(repr(round(float(value),4))).normalize(),'f')
    return text


def matches_source(value, numbers):
    """The model's value is one of the source's numbers: exactly, or (with at least two decimals) the source number
    rounded to the decimals the value is written in, so 92.07 binds to a stored 92.06999969482422 but 92.1 does not."""
    if value in numbers:return True
    places=-value.as_tuple().exponent
    if places<2:return False
    step=Decimal(1).scaleb(-places)
    return any(n.quantize(step,rounding=ROUND_HALF_UP)==value for n in numbers if n.is_finite())


def _as_decimal(value):
    """A recorded or recomputed figure as a Decimal: int, float (via its repr), Decimal or a numeric string."""
    if isinstance(value,bool) or value is None:raise TypeError('not a figure')
    if isinstance(value,Decimal):return value
    if isinstance(value,float):return Decimal(repr(value))
    if isinstance(value,(int,str)):return Decimal(value.strip() if isinstance(value,str) else value)
    raise TypeError('not a figure')


def agrees_at_recorded_precision(recomputed, recorded):
    """A recomputed value agrees with a recorded one when it rounds (half-up, as ``matches_source``) to the recorded
    value's own decimal places and equals it there.  The tolerance is the recording's precision and nothing wider:
    3218 agrees with 3218.00, 1258.4 with 1258.41, 391.1 with 391.05; 1258.4 does not agree with 1259.9."""
    try:
        with localcontext() as ctx:
            ctx.prec=60
            want=_as_decimal(recorded);got=_as_decimal(recomputed)
            if not want.is_finite() or not got.is_finite():return False
            places=max(0,-want.as_tuple().exponent)
            return got.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)==want
    except (InvalidOperation,TypeError,ValueError):return False


def _figure_text(text):
    """A text as the figure reader reads it: NFKC, the traditional forms folded, periods, accessions and ids removed,
    thousands commas joined.  ``source_numbers`` and the receipts' suffix check read the same text."""
    text=unicodedata.normalize('NFKC',text).replace('萬','万').replace('億','亿')
    text=PERIOD_TEXT.sub(' ',ACCESSION.sub(' ',SOURCE_ID.sub(' ',TASK_ID.sub(' ',text))))
    return re.sub(r'(?<=\d),(?=\d{3}(?!\d))','',text)


def source_numbers(text):
    """The numbers one text states, as a calculation input may bind them: in full, and (for "331,839 百万美元")
    the unit-less digits too, so a value can be computed in millions."""
    found=figure_tokens(_figure_text(text))
    return {Decimal(n)*Decimal(str(_MAGNITUDE.get(unit.lower(),1))) for n,unit in found}|{Decimal(n) for n,unit in found if unit}


def user_numbers(user_text):
    """The numbers the user wrote, Chinese numerals included (五万 binds as 50000 as well as 5万's 5)."""
    from .evidence import user_figure_values
    return source_numbers(user_text)|{Decimal(str(v)) for v in user_figure_values(user_text)}


# A literal in an expression: an integer or decimal of at most 1000 in size and four decimals.
MAX_LITERAL=Decimal(1000)
MAX_LITERAL_DECIMALS=4


# Literals the reconciliation never rewrites to an input: CONSTANTS, and 2 (a plain factor the reader sees; it is not in CONSTANTS).
RECONCILE_EXEMPT=CONSTANTS|{2}


class _Unbound(Exception):pass


def _bind_literals(tree,values):
    """Literal reconciliation: a formula that writes a sourced input's number out in full ("(507.12-521.91)/521.91*100")
    is rewritten to the input names, so it then passes the same checks as any named formula.  Every literal that is not
    a constant must equal exactly one input's value; an unmatched or ambiguous literal means no binding (``None``)."""
    class Rename(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) not in (int,float) or node.value in RECONCILE_EXEMPT:return node
            matches=[name for name,value in values.items() if value==Decimal(str(node.value))]
            if len(matches)!=1:raise _Unbound()
            return ast.copy_location(ast.Name(id=matches[0],ctx=ast.Load()),node)
    try:return Rename().visit(tree)
    except _Unbound:return None


class CalculationUnbound(ValueError):
    """An input bound to no source.  ``receipts`` has one entry per input (every input is judged first).  ``str`` is the
    bare code, so every ``except ValueError`` and every ``match='calculation_input_unbound'`` still holds."""
    def __init__(self,receipts):
        super().__init__('calculation_input_unbound')
        self.receipts=receipts


# The sentences a receipt carries: FP7 decision D-F2, verbatim.  %d is the citation ordinal, %s the unrecognised suffix.
NEXT_ACTION={
    'origin_invalid':'每个输入必须且只能有一个出处：source_ordinal（资料）或 user_stated（用户原话）；name 必须是单个小写字母且不重复。',
    'source_not_cited':'本轮没有这个序号的引用。只能使用本轮工具结果里已经给出的 [n]。',
    'value_not_finite':'数值必须是有限的十进制数。',
    'value_not_in_user_words':'这个数不在用户本轮的原话里；只有用户亲自写出的数才能标 user_stated。它若来自资料，请改用 source_ordinal 指向那条资料。',
    'bound':'',
    'token_suffix_unrecognized':'引用 [%d] 里这个数后面紧跟着系统不认识的后缀「%s」，所以无法绑定。这是系统解析的限制，不是你的输入有误；可以改用同一资料里写法完整的数，或换一条资料。',
    'value_in_other_source':'这个数不在引用 [%d] 里，但出现在 other_ordinals 所列引用的可核对文本里。这只是候选：请自行确认是同一指标、同一期间后，再改用那条引用的序号。',
    'value_not_in_source':'引用 [%d] 的可核对文本里没有这个数。请先核对序号；资料里若是不同单位或不同精度的写法，按资料里的写法传入，换算写进 expression。',
}

# Reasons whose receipt also names the nearest numbers the cited source does hold.
_CLOSEST={'token_suffix_unrecognized','value_in_other_source','value_not_in_source'}


def _declared_origin(ordinal,stated):
    if stated and ordinal is None:return 'user_stated'
    if ordinal is not None and not stated:return 'source_ordinal:%s'%ordinal
    return 'invalid'


def _closest(value,numbers):
    """At most three of the source's numbers, nearest the requested value by relative difference."""
    def gap(number):return abs(number-value)/abs(value) if value else abs(number)
    return [str(number) for number in sorted(numbers,key=lambda number:(gap(number),str(number)))[:3]]


def _matched_token(value,numbers):
    """The source number a value binds to, as ``matches_source`` reads it: an equal number, else one that rounds
    to the value's own decimals (92.06999969482422 for 92.07).  ``None`` when none does."""
    equal=sorted((number for number in numbers if number==value),key=str)
    if equal:return str(equal[0])
    places=-value.as_tuple().exponent
    if places<2:return None
    step=Decimal(1).scaleb(-places)
    try:rounded=sorted((number for number in numbers if number.is_finite() and number.quantize(step,rounding=ROUND_HALF_UP)==value),key=str)
    except InvalidOperation:return None
    return str(rounded[0]) if rounded else None


def _source_reason(requested,value,ordinal,source,citations):
    """Why a source input did not bind, judged top to bottom as the FP7 table gives: ``(reason, detail)``."""
    from .evidence import citation_check_text
    suffix=re.search(r'(?<![\d.])'+re.escape(requested)+r'([A-Za-z]+)',_figure_text(citation_check_text(source)))
    if suffix:return 'token_suffix_unrecognized',{'suffix':suffix.group(1)}
    others=sorted(c['ordinal'] for c in citations if c['ordinal']!=ordinal and matches_source(value,source_numbers(citation_check_text(c))))
    if others:return 'value_in_other_source',{'others':others}
    return 'value_not_in_source',{}


def _receipt(item,ordinal,stated,value,reason,*,numbers=(),selected=None,suffix='',others=()):
    """One input's receipt, with the fixed keys the model and the record read."""
    found=reason=='bound'
    receipt={'name':item.get('name'),'requested_value':str(item.get('value')),'declared_origin':_declared_origin(ordinal,stated),
             'found':found,'selected_token':selected if found else None,'parsed_value':None if value is None else str(value),
             'reason':reason,'next_action':NEXT_ACTION[reason]}
    if reason=='token_suffix_unrecognized':receipt['next_action']=NEXT_ACTION[reason]%(ordinal,suffix)
    elif reason in ('value_in_other_source','value_not_in_source'):receipt['next_action']=NEXT_ACTION[reason]%ordinal
    if reason in _CLOSEST:receipt['closest_in_source']=_closest(value,numbers)
    if reason=='value_in_other_source':receipt['other_ordinals']=list(others)[:5]
    return receipt


def calculate(args, citations, user_text=''):
    """``user_text`` is what the person typed (``Turn.user_stated_text``); an input marked ``user_stated`` must be
    one of its figures.  ``None`` is a replay of a stored calculation: its user-stated inputs were bound when
    it was made and the person's words are no longer at hand, so they are taken as recorded."""
    from .evidence import citation_check_text
    expression=args['expression']
    if not isinstance(expression,str) or len(expression)>200:raise ValueError('invalid_calculation')
    indexed={c['ordinal']:c for c in citations};values={};parents=[];recorded=[]
    # FP7: with the receipts on, every input is judged and each unbound one gets its receipt; off, the first one
    # raises the bare code, as it always did.
    judged=flag('FINBOT_FP7_INPUT_RECEIPTS',True);receipts=[]
    for item in args['inputs']:
        name=item['name']
        ordinal=item.get('source_ordinal');stated=bool(item.get('user_stated'))
        source=indexed.get(ordinal)
        # Exactly one origin per operand: a cited source, or the user's own words.
        origin_bad=not re.fullmatch(r'[a-z]',name) or name in values or stated==(ordinal is not None)
        if origin_bad or (not stated and not source):
            if not judged:raise ValueError('calculation_input_unbound')
            receipts.append(_receipt(item,ordinal,stated,None,'origin_invalid' if origin_bad else 'source_not_cited'));continue
        try:value=Decimal(item['value'])
        except (InvalidOperation,TypeError):raise ValueError('invalid_calculation')
        if not value.is_finite():
            if not judged:raise ValueError('calculation_input_unbound')
            receipts.append(_receipt(item,ordinal,stated,value,'value_not_finite'));continue
        selected=None
        if stated:
            if user_text is not None and not matches_source(value,user_numbers(user_text)):
                if not judged:raise ValueError('calculation_input_unbound')
                receipts.append(_receipt(item,ordinal,stated,value,'value_not_in_user_words'));continue
            recorded.append({**item,'origin':'user_stated'})
        else:
            numbers=source_numbers(citation_check_text(source))
            if not matches_source(value,numbers):
                if not judged:raise ValueError('calculation_input_unbound')
                reason,detail=_source_reason(str(item.get('value')),value,ordinal,source,citations)
                receipts.append(_receipt(item,ordinal,stated,value,reason,numbers=numbers,**detail));continue
            parents.append(ordinal);recorded.append(item)
            selected=_matched_token(value,numbers) if judged else None
        values[name]=value
        if judged:receipts.append(_receipt(item,ordinal,stated,value,'bound',selected=selected))
    if any(not receipt['found'] for receipt in receipts):raise CalculationUnbound(receipts)
    if not values or len(values)>8:raise ValueError('invalid_calculation')
    constants=[]
    def evaluate(node,env):
        if isinstance(node,ast.Name) and node.id in env:return env[node.id]
        if isinstance(node,ast.Constant) and type(node.value) is int and node.value in CONSTANTS:return Decimal(node.value)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            # A literal the reader can see in the expression: it adds no figure to the world, and the result records it.
            literal=Decimal(str(node.value))
            if not literal.is_finite() or abs(literal)>MAX_LITERAL or -literal.as_tuple().exponent>MAX_LITERAL_DECIMALS:raise ValueError('invalid_calculation')
            if literal not in CONSTANTS and str(node.value) not in constants:constants.append(str(node.value))
            return literal
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=evaluate(node.operand,env);return value if isinstance(node.op,ast.UAdd) else -value
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Pow):
            base=evaluate(node.left,env);exp=evaluate(node.right,{})
            if exp==0 or abs(exp)>Decimal(20) or (base<0 and exp!=int(exp)):raise ValueError('invalid_calculation')
            return Decimal(str(float(base)**float(exp)))
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            left,right=evaluate(node.left,env),evaluate(node.right,env)
            if isinstance(node.op,ast.Add):return left+right
            if isinstance(node.op,ast.Sub):return left-right
            if isinstance(node.op,ast.Mult):return left*right
            return left/right
        raise ValueError('invalid_calculation')
    try:
        tree=ast.parse(expression,mode='eval')
        if len(list(ast.walk(tree)))>80:raise ValueError('invalid_calculation')
        if {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}!=set(values):
            # Names and inputs disagree: the formula may have written an input's number out in full.  Rewrite
            # those literals to the input names, then run every check below on the rewritten formula, unchanged.
            tree=_bind_literals(tree,values)
            if tree is None or {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}!=set(values):raise ValueError('invalid_calculation')
            expression=ast.unparse(tree.body)
        decimals=args.get('decimals',2)
        if type(decimals) is not int or not 0<=decimals<=8:raise ValueError('invalid_calculation')
        with localcontext() as ctx:
            ctx.prec=50
            value=evaluate(tree.body,values)
            if not value.is_finite() or abs(value)>Decimal('1e24'):raise ValueError('invalid_calculation')
            # Laundering guard: literals make any number reachable (a*0+394).  The result has to move when the
            # inputs do.  Each input is scaled by a different factor: doubling them all would leave every ratio
            # (a/b, (a-b)/b*100) unchanged and refuse the most ordinary calculation there is.
            moved={name:values[name]*(index+2) for index,name in enumerate(sorted(values))}
            if evaluate(tree.body,moved)==value:raise ValueError('invalid_calculation')
            value=value.quantize(Decimal(1).scaleb(-decimals))
    except (SyntaxError,ArithmeticError,RecursionError) as exc:raise ValueError('invalid_calculation') from exc
    result={'value':str(value),'expression':expression,'inputs':recorded,'parents':sorted(set(parents)),'derived':True}
    if constants:result['constants']=constants
    return result


def bindable_values(citations, args):
    """The numbers a model may bind from the cited sources, as strings.

    ``calculation_input_unbound`` is unhelpful on its own: the model then guesses another value
    and the same call fails again. Handing back what the source actually contains ends the loop.
    """
    indexed={c['ordinal']:c for c in citations or []}
    found={}
    for item in args.get('inputs') or []:
        ordinal=item.get('source_ordinal') if isinstance(item,dict) else None
        source=indexed.get(ordinal)
        if not source:continue
        from .evidence import citation_check_text
        text=unicodedata.normalize('NFKC',citation_check_text(source)).replace('萬','万').replace('億','亿')
        text=PERIOD_TEXT.sub(' ',ACCESSION.sub(' ',SOURCE_ID.sub(' ',TASK_ID.sub(' ',text))))
        text=re.sub(r'(?<=\d),(?=\d{3}(?!\d))','',text)
        values=[str(Decimal(n)*Decimal(str(_MAGNITUDE.get(unit.lower(),1)))) for n,unit in figure_tokens(text)]
        if values:found[str(ordinal)]=values[:12]
    return found
