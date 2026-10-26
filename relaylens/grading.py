"""Strict JSON contracts, shared by task and tool-result graders."""
import json
import math


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('non-finite JSON constant: ' + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def exact(actual, expected):
    """JSON types matter: true is not 1, 1.0 is not an integer contract."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(exact(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(exact(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, float) and not math.isfinite(actual):
        return False
    return actual == expected
