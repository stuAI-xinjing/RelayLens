"""Fresh synthetic tasks, ground-truth solvers, and deterministic graders.

No model-generated code is executed. Code-repair microtasks use an AST
interpreter for expressions, then run unseen randomized and boundary cases.
"""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
import math
import operator
import random
from dataclasses import dataclass

SUITE_VERSION = "synthetic-2"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


@dataclass
class Task:
    id: str
    family: str
    prompt: str
    expected: object
    metadata: dict

    @property
    def prompt_hash(self):
        return digest(self.prompt)

    def grade(self, text: str) -> dict:
        text = text.strip()
        if self.family == "instruction":
            return {"passed": text == self.expected, "format_passed": text == self.expected,
                    "reason": "exact text match", "expected": self.expected}
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {"passed": False, "format_passed": False, "reason": "JSON only required"}
        if self.family == "code_repair":
            return grade_expression(parsed, self.metadata)
        passed = parsed == self.expected
        return {"passed": passed, "format_passed": True,
                "reason": "exact structured answer", "expected": self.expected, "parsed": parsed}


def constraint_ok(order, c):
    pos = {x: i for i, x in enumerate(order)}
    kind, a, b = c[:3]
    if kind == "before":
        return pos[a] < pos[b]
    if kind == "gap":
        return abs(pos[a] - pos[b]) == c[3]
    if kind == "apart":
        return abs(pos[a] - pos[b]) != 1
    if kind == "between":
        return min(pos[a], pos[b]) < pos[c[3]] < max(pos[a], pos[b])
    raise ValueError(kind)


def ordering(rng, index):
    labels = list("ABCDEFG")
    target = rng.sample(labels, 7)
    positions = {x: i for i, x in enumerate(target)}
    pool = []
    for a, b in itertools.permutations(labels, 2):
        if positions[a] < positions[b]:
            pool.append(("before", a, b))
        pool.append(("gap", a, b, abs(positions[a] - positions[b])))
        if abs(positions[a] - positions[b]) != 1:
            pool.append(("apart", a, b))
    for a, b, c in itertools.permutations(labels, 3):
        if min(positions[a], positions[b]) < positions[c] < max(positions[a], positions[b]):
            pool.append(("between", a, b, c))
    rng.shuffle(pool)
    candidates = list(itertools.permutations(labels))
    constraints = []
    for c in pool:
        narrowed = [p for p in candidates if constraint_ok(p, c)]
        if len(narrowed) < len(candidates):
            constraints.append(c)
            candidates = narrowed
        if len(candidates) == 1:
            break
    assert len(candidates) == 1
    lines = []
    for c in constraints:
        k, a, b = c[:3]
        if k == "before": lines.append(f"{a} is before {b}.")
        elif k == "apart": lines.append(f"{a} and {b} are not adjacent.")
        elif k == "gap": lines.append(f"The absolute position difference between {a} and {b} is {c[3]}.")
        else: lines.append(f"{c[3]} is strictly between {a} and {b} (either direction).")
    prompt = "Arrange A,B,C,D,E,F,G at positions 1..7. There is exactly one solution.\n"
    prompt += "\n".join(f"{i+1}. {s}" for i, s in enumerate(lines))
    prompt += '\nReturn ONLY a JSON array of the seven labels in left-to-right order.'
    return Task(f"logic-{index}", "logic", prompt, list(candidates[0]),
                {"constraints": constraints, "unique_solutions": 1})


def arithmetic(rng, index):
    items = rng.randint(80, 600)
    per_box = rng.randint(5, 19)
    delivered = rng.randint(2, 9)
    returned = rng.randint(1, 15)
    available = items + delivered * per_box - returned
    prompt = (f"A store has {items} items. It receives {delivered} boxes of {per_box} items, "
              f"then sends back {returned} items. It repacks everything into full boxes of {per_box}. "
              "The manager is 42 years old; this is irrelevant. "
              'Return ONLY JSON {"full_boxes": integer, "remaining": integer}.')
    return Task(f"arithmetic-{index}", "arithmetic", prompt,
                {"full_boxes": available // per_box, "remaining": available % per_box}, {})


def instruction(rng, index):
    nonce = f"CHECK-{rng.getrandbits(40):010X}"
    numbers = rng.sample(range(1, 80), 9)
    threshold = rng.randint(20, 55)
    expected = ",".join(map(str, sorted(x for x in numbers if x >= threshold))) or "EMPTY"
    prompt = (f"Numbers: {numbers}. Keep numbers >= {threshold}, sort ascending, join with commas "
              "and no spaces; if none remain use EMPTY. Return exactly TWO lines: "
              f"line 1 is {nonce}; line 2 is the result. No Markdown, explanations or blank lines.")
    return Task(f"instruction-{index}", "instruction", prompt, nonce + "\n" + expected, {})


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
CMPS = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
        ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def evaluate_expression(expression: str, variables: dict):
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("expression too complex for this microtask")
    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float, bool):
            if abs(node.value) > 10**9: raise ValueError("constant outside microtask range")
            return node.value
        if isinstance(node, ast.Name) and node.id in variables: return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            result = OPS[type(node.op)](visit(node.left), visit(node.right))
            if abs(result) > 10**15: raise ValueError("numeric overflow")
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else (+value if isinstance(node.op, ast.UAdd) else not value)
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op, right_node in zip(node.ops, node.comparators):
                if type(op) not in CMPS: raise ValueError("unsupported comparison")
                right = visit(right_node)
                if not CMPS[type(op)](left, right): return False
                left = right
            return True
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [bool(visit(v)) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.IfExp): return visit(node.body if visit(node.test) else node.orelse)
        raise ValueError("return a pure arithmetic/boolean expression; calls and attributes are not part of this task")
    return visit(tree)


def code_repair(rng, index):
    kind = index % 3
    cases = []
    if kind == 0:
        contract = "def inside(x, lo, hi):\n    return lo < x < hi"
        instruction_text = "Fix inclusive boundaries: inside must be true iff lo <= x <= hi."
        canonical = "lo <= x <= hi"
        for _ in range(12):
            lo = rng.randint(-20, 10); hi = lo + rng.randint(1, 10)
            for x in (lo-1, lo, (lo+hi)/2, hi, hi+1): cases.append({"x": x, "lo": lo, "hi": hi})
    elif kind == 1:
        contract = "def weighted(a, b, wa, wb):\n    return (a + b) / (wa + wb)"
        instruction_text = "Return the weighted mean; wa, wb are positive weights."
        canonical = "(a*wa + b*wb)/(wa+wb)"
        cases = [dict(a=rng.randint(-20,40), b=rng.randint(-30,50), wa=rng.randint(1,10), wb=rng.randint(1,10)) for _ in range(60)]
    else:
        contract = "def boxes(n, size):\n    return n / size"
        instruction_text = "Return the integer number of full boxes; n>=0 and size>0."
        canonical = "n // size"
        cases = [dict(n=rng.randint(0,200), size=rng.randint(2,12)) for _ in range(60)]
        cases += [{"n":0,"size":3},{"n":7,"size":3}]
    prompt = ("Repair this Python microtask:\n" + contract + "\n" + instruction_text +
              '\nReturn ONLY JSON {"expression":"replacement return expression"}. '
              "Use only numeric literals, existing variable names, arithmetic, comparisons, boolean operators or conditional expressions. No function calls.")
    return Task(f"code-{index}", "code_repair", prompt, canonical,
                {"cases": cases, "canonical": canonical, "require_integer": kind == 2})


def grade_expression(parsed, meta):
    if not isinstance(parsed, dict) or set(parsed) != {"expression"} or not isinstance(parsed["expression"], str):
        return {"passed": False, "format_passed": False, "reason": "expression object required"}
    matched = 0
    try:
        for variables in meta["cases"]:
            expected = evaluate_expression(meta["canonical"], variables)
            actual = evaluate_expression(parsed["expression"], variables)
            typed = type(actual) is bool if type(expected) is bool else type(actual) in (int, float)
            if meta["require_integer"]: typed = type(actual) is int
            if typed and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9): matched += 1
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return {"passed": False, "format_passed": True, "reason": "invalid expression or evaluation failed"}
    return {"passed": matched == len(meta["cases"]), "format_passed": True,
            "reason": "unseen numerical and boundary cases", "cases_passed": matched,
            "cases_total": len(meta["cases"])}


def suite(seed: int, rounds: int) -> list[Task]:
    result = []
    for i in range(rounds):
        for j, builder in enumerate((ordering, arithmetic, code_repair, instruction)):
            result.append(builder(random.Random(seed + i * 7919 + j * 104729), i))
    random.Random(seed + 31).shuffle(result)
    return result
