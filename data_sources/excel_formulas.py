"""安全计算 Excel 导入所需的常见单元格公式。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_TOKEN = re.compile(r'\s*(?:(\$?[A-Za-z]{1,3}\$?\d+)|("(?:[^"]|"")*")|(\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?|\.\d+(?:[Ee][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_.]*)|(<=|>=|<>|[=<>+*/^(),-]))')


class _Parser:
    def __init__(self, formula: str) -> None:
        self.tokens = []
        position = 0
        expression = formula.lstrip("=")
        while position < len(expression):
            match = _TOKEN.match(expression, position)
            if not match:
                raise ValueError(f"unsupported formula syntax near {expression[position:position + 20]!r}")
            cell, string, number, identifier, operator = match.groups()
            if cell:
                token = ("cell", cell.replace("$", "").upper())
            elif string:
                token = ("string", string[1:-1].replace('""', '"'))
            elif number:
                token = ("number", number)
            elif identifier:
                token = ("identifier", identifier.upper())
            else:
                token = ("operator", operator)
            self.tokens.append(token)
            position = match.end()
        self.tokens.append(("eof", ""))
        self.position = 0

    def peek(self, value: str | None = None) -> bool:
        kind, token = self.tokens[self.position]
        return token == value if value is not None else kind == "eof"

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.tokens[self.position]
        if value is not None and token[1] != value:
            raise ValueError(f"expected {value!r} in formula")
        self.position += 1
        return token

    def parse(self) -> Any:
        value = self.comparison()
        if not self.peek():
            raise ValueError("unexpected trailing formula content")
        return value

    def comparison(self) -> Any:
        value = self.additive()
        if self.tokens[self.position][1] in {"=", "<>", "<", ">", "<=", ">="}:
            return ("binary", self.take()[1], value, self.additive())
        return value

    def additive(self) -> Any:
        value = self.multiplicative()
        while self.peek("+") or self.peek("-"):
            value = ("binary", self.take()[1], value, self.multiplicative())
        return value

    def multiplicative(self) -> Any:
        value = self.power()
        while self.peek("*") or self.peek("/"):
            value = ("binary", self.take()[1], value, self.power())
        return value

    def power(self) -> Any:
        value = self.unary()
        if self.peek("^"):
            self.take("^")
            return ("binary", "^", value, self.power())
        return value

    def unary(self) -> Any:
        if self.peek("+") or self.peek("-"):
            return ("unary", self.take()[1], self.unary())
        return self.primary()

    def primary(self) -> Any:
        kind, value = self.tokens[self.position]
        if kind in {"number", "string", "cell"}:
            self.take()
            return ("literal" if kind != "cell" else "cell", Decimal(value) if kind == "number" else value)
        if kind == "identifier":
            name = self.take()[1]
            if not self.peek("("):
                raise ValueError(f"unsupported formula name {name!r}")
            self.take("(")
            args = []
            if not self.peek(")"):
                args.append(self.comparison())
                while self.peek(","):
                    self.take(",")
                    args.append(self.comparison())
            self.take(")")
            return ("function", name, args)
        if self.peek("("):
            self.take("(")
            value = self.comparison()
            self.take(")")
            return value
        raise ValueError(f"unexpected token {value!r} in formula")


class ExcelFormulaEvaluator:
    """计算算术与 IF 公式；其他函数、跨表引用一律清晰报错。"""

    def __init__(self, worksheet) -> None:
        self.worksheet = worksheet
        self.cache: dict[str, Any] = {}
        self.active: set[str] = set()

    def value(self, coordinate: str) -> Any:
        if coordinate in self.cache:
            return self.cache[coordinate]
        if coordinate in self.active:
            raise ValueError(f"circular formula reference at {coordinate}")
        self.active.add(coordinate)
        try:
            raw = self.worksheet[coordinate].value
            result = self.evaluate(_Parser(raw).parse()) if isinstance(raw, str) and raw.startswith("=") else self.coerce(raw)
            self.cache[coordinate] = result
            return result
        except (InvalidOperation, ArithmeticError, ValueError, TypeError) as exc:
            raise ValueError(f"cannot calculate formula at {coordinate}: {self.worksheet[coordinate].value!r} ({exc})") from exc
        finally:
            self.active.remove(coordinate)

    @staticmethod
    def coerce(value: Any) -> Any:
        if value is None:
            return Decimal(0)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        return value

    @staticmethod
    def number(value: Any) -> Decimal:
        if isinstance(value, bool):
            return Decimal(int(value))
        try:
            return value if isinstance(value, Decimal) else Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"expected numeric value, got {value!r}") from exc

    def evaluate(self, node: Any) -> Any:
        kind = node[0]
        if kind == "literal":
            return node[1]
        if kind == "cell":
            return self.value(node[1])
        if kind == "unary":
            value = self.number(self.evaluate(node[2]))
            return value if node[1] == "+" else -value
        if kind == "function":
            name, args = node[1], node[2]
            if name != "IF" or len(args) not in {2, 3}:
                raise ValueError(f"unsupported function {name} or invalid argument count")
            condition = self.evaluate(args[0])
            truth = bool(self.number(condition)) if isinstance(condition, (Decimal, int, float, bool)) else bool(condition)
            return self.evaluate(args[1]) if truth else (self.evaluate(args[2]) if len(args) == 3 else False)
        _, operator, left_node, right_node = node
        left, right = self.evaluate(left_node), self.evaluate(right_node)
        if operator in {"=", "<>", "<", ">", "<=", ">="}:
            try:
                left, right = self.number(left), self.number(right)
            except ValueError:
                pass
            if operator == "=": return left == right
            if operator == "<>": return left != right
            if operator == "<": return left < right
            if operator == ">": return left > right
            if operator == "<=": return left <= right
            return left >= right
        left, right = self.number(left), self.number(right)
        if operator == "+": return left + right
        if operator == "-": return left - right
        if operator == "*": return left * right
        if operator == "/": return left / right
        if operator == "^":
            if right != right.to_integral_value(): raise ValueError("only integral exponents are supported")
            return left ** int(right)
        raise ValueError(f"unsupported operator {operator!r}")


def formula_result_as_text(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "" if value is None else str(value)
