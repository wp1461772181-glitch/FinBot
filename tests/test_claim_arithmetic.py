from decimal import Decimal
from app.agent_workflow.claim_arithmetic import evaluate


def test_only_bounded_named_four_operation_arithmetic():
    assert evaluate('a-b', {'a': '41.5', 'b': '40.1'}) == Decimal('1.4')
    assert evaluate('a/zero', {'a': '1', 'zero': '0'}) is None
    assert evaluate('__import__("os")', {'a': '1'}) is None
    assert evaluate('a+2', {'a': '1'}) is None
    assert evaluate('a', {'a': '1', 'b': '2'}) is None
    assert evaluate('a**b', {'a': '2', 'b': '3'}) is None
