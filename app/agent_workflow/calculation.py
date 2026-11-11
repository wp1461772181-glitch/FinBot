"""Small Decimal arithmetic over inputs present in this turn's accepted sources."""
import ast
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from .semantic import _MAGNITUDE, PERIOD_TEXT, ACCESSION, SOURCE_ID, TASK_ID, figure_tokens
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


def source_numbers(text):
    """The numbers one text states, as a calculation input may bind them: in full, and (for "331,839 百万美元")
    the unit-less digits too, so a value can be computed in millions."""
    text=unicodedata.normalize('NFKC',text).replace('萬','万').replace('億','亿')
    text=PERIOD_TEXT.sub(' ',ACCESSION.sub(' ',SOURCE_ID.sub(' ',TASK_ID.sub(' ',text))))
    text=re.sub(r'(?<=\d),(?=\d{3}(?!\d))','',text)
    found=figure_tokens(text)
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


def calculate(args, citations, user_text=''):
    """``user_text`` is what the person typed (``Turn.user_stated_text``); an input marked ``user_stated`` must be
    one of its figures.  ``None`` is a replay of a stored calculation: its user-stated inputs were bound when
    it was made and the person's words are no longer at hand, so they are taken as recorded."""
    from .evidence import citation_check_text
    expression=args['expression']
    if not isinstance(expression,str) or len(expression)>200:raise ValueError('invalid_calculation')
    indexed={c['ordinal']:c for c in citations};values={};parents=[];recorded=[]
    for item in args['inputs']:
        name=item['name']
        ordinal=item.get('source_ordinal');stated=bool(item.get('user_stated'))
        source=indexed.get(ordinal)
        # Exactly one origin per operand: a cited source, or the user's own words.
        if not re.fullmatch(r'[a-z]',name) or name in values or stated==(ordinal is not None) or (not stated and not source):
            raise ValueError('calculation_input_unbound')
        try:value=Decimal(item['value'])
        except (InvalidOperation,TypeError):raise ValueError('invalid_calculation')
        if not value.is_finite():raise ValueError('calculation_input_unbound')
        if stated:
            if user_text is not None and not matches_source(value,user_numbers(user_text)):raise ValueError('calculation_input_unbound')
            recorded.append({**item,'origin':'user_stated'})
        else:
            if not matches_source(value,source_numbers(citation_check_text(source))):raise ValueError('calculation_input_unbound')
            parents.append(ordinal);recorded.append(item)
        values[name]=value
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
