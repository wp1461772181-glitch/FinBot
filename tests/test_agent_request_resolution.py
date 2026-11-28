"""C2/C7/C9 replace legacy text slot extraction with typed model-provided arguments."""
import pytest
from app.agent_tool_catalog import validate

@pytest.mark.parametrize('args',[{'query':'news','days_back':0},{'query':'news','days_back':367},{'query':'news','max_results':0},{'query':'news','unknown':1}])
def test_tool_arguments_are_schema_validated(args):
    with pytest.raises(ValueError):validate('web_research',args)

@pytest.mark.parametrize('symbol',['AMD','MU','RBLX','ZZZZ','BRK.B'])
def test_symbol_format_does_not_require_a_company_directory(symbol):
    assert validate('query_stock_prices',{'symbol':symbol})['symbol']==symbol
