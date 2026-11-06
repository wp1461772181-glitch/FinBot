"""Bounded arithmetic evaluation of a model's proposed operand values."""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation, localcontext


def evaluate(expression: str, values: dict[str, str]) -> Decimal | None:
    """Evaluate named operands and four operations; no constants, calls or implicit relations."""
    if not isinstance(expression, str) or len(expression) > 200 or not 1 <= len(values) <= 6:
        return None
    try:
        parsed = ast.parse(expression, mode='eval')
        if sum(1 for _ in ast.walk(parsed)) > 32:
            return None
        numbers = {name: Decimal(value) for name, value in values.items()}
        if any(not n.is_finite() or abs(n) > Decimal('1e18') for n in numbers.values()):
            return None
        used = set()
        def walk(node):
            if isinstance(node, ast.Name) and node.id in numbers:
                used.add(node.id)
                return numbers[node.id]
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                left, right = walk(node.left), walk(node.right)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                return left / right
            raise ValueError('unsupported expression')
        with localcontext() as context:
            context.prec = 28
            result = walk(parsed.body)
        if used != set(numbers) or not result.is_finite() or abs(result) > Decimal('1e18'):
            return None
        return result
    except (SyntaxError, ValueError, TypeError, InvalidOperation, ZeroDivisionError, ArithmeticError):
        return None
