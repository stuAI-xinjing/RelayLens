"""Decimal dashboard units; exact counts stay visible."""
import math


def format_tokens(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return '未记录'
    return f'{value:,.0f} Token · {value/1000:,.3f}K · {value/1000000:,.6f}M'


def token_rows(audit):
    totals = dict(audit.get('totals') or {})
    parts = [totals.get(k) for k in ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')]
    if all(type(n) in (int, float) and math.isfinite(n) and n >= 0 for n in parts):
        ordinary = parts[0] - parts[1] - parts[2]
        if ordinary >= 0:
            totals['ordinary_input_tokens'] = ordinary
    labels = [('total_tokens', '总量（输入＋输出）'),
              ('input_tokens', '输入总量（含缓存）'),
              ('ordinary_input_tokens', '普通输入（扣除缓存读取/写入）'),
              ('output_tokens', '输出总量（含隐藏推理）'),
              ('cache_read_tokens', '其中：缓存读取'),
              ('cache_write_tokens', '其中：缓存写入'),
              ('reasoning_tokens', '其中：隐藏推理')]
    return [{'field': key, 'label': label, 'value': totals.get(key),
             'display': format_tokens(totals.get(key))} for key, label in labels]
