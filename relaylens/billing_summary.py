"""Read displayed dashboard aggregates without inventing per-request evidence.

K/M shorthand is decimal and retains the interval implied by display precision.
These are provider claims; even matching aggregates do not establish token truth.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re

from .token_audit import summarize_report

_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*[kKmM]?'
_MONEY = rf'(?:(?:USD|CNY|RMB)\s*|[$¥￥]\s*)?{_NUMBER}'
_MODEL = r'(?:gpt|claude|qwen|o[134])[-.a-zA-Z0-9_:/]*'
_HEADER = re.compile(r'模型\s+请求(?:数)?\s+Tokens?\s+实际(?:消费)?\s+标准', re.I)
_ROW = re.compile(rf'(?P<model>{_MODEL})\s+(?P<request_count>\d+)\s+(?P<total_tokens>{_NUMBER})\s+(?P<actual_cost>{_MONEY})\s+(?P<standard_cost>{_MONEY})(?![\d.])', re.I)
_LABELS = {
    'request_count': r'(?:总请求数|请求总数)',
    'total_tokens': r'(?:总\s*Tokens?|Token\s*总数)',
    'input_display_tokens': r'(?:输入)',
    'output_tokens': r'(?:输出)',
    'cache_read_tokens': r'(?:缓存读取|缓存)',
    'cache_write_tokens': r'(?:缓存写入)',
    'actual_cost': r'(?:总消费|实际消费|实际扣费)',
    'standard_cost': r'(?:标准)',
}


def _display(raw, span, *, money=False, count=False):
    """Half-last-unit interval; unabridged integer token counts are exact."""
    clean = re.sub(r'^(?:USD|CNY|RMB|[$¥￥])\s*', '', raw.strip(), flags=re.I)
    match = re.fullmatch(r'([\d,]+)(?:\.(\d+))?\s*([kKmM]?)', clean)
    if not match:
        return None
    decimals, suffix = match.group(2) or '', match.group(3).upper()
    try:
        scale = Decimal({'K': '1000', 'M': '1000000'}.get(suffix, '1'))
        value = Decimal(match.group(1).replace(',', '') + ('.' + decimals if decimals else '')) * scale
        rounded = bool(suffix or decimals or money) and not count
        half = scale * Decimal(10) ** -len(decimals) / 2 if rounded else Decimal(0)
        if not value.is_finite() or value < 0 or value > Decimal('1e18'):
            return None
        result = {'value': float(value), 'lower': float(max(Decimal(0), value-half)),
                  'upper': float(value+half), 'raw': raw.strip(), 'rounded': rounded,
                  'source_span': list(span)}
        if money:
            result['currency'] = 'USD' if '$' in raw or 'USD' in raw.upper() else 'CNY' if any(s in raw.upper() for s in ('CNY', 'RMB', '¥', '￥')) else None
        return result
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _overlap(a, b):
    return max(a['lower'], b['lower']) <= min(a['upper'], b['upper'])


def _infer_input(fields, issues):
    displayed = fields.get('input_display_tokens')
    total, output, cached = (fields.get(k) for k in ('total_tokens', 'output_tokens', 'cache_read_tokens'))
    if not displayed or not total or not output:
        return
    def matches(parts):
        return _overlap(total, {'lower': sum(p['lower'] for p in parts), 'upper': sum(p['upper'] for p in parts)})
    included = matches([displayed, output])
    excluded = cached is not None and matches([displayed, output, cached] + ([fields['cache_write_tokens']] if 'cache_write_tokens' in fields else []))
    if excluded and not included:
        fields['input_uncached_tokens'] = dict(displayed, semantics='inferred_from_displayed_total')
    elif included and not excluded:
        fields['input_tokens'] = dict(displayed, semantics='inferred_from_displayed_total')
    elif not included and not excluded and cached:
        issues.append('displayed_token_parts_do_not_sum_to_total')


def parse_summary(text):
    """Extract model tables/cards. Never sum repeated dashboard sections."""
    result = {'status': 'not_recognized', 'source': 'pasted_dashboard_summary',
              'aggregates': [], 'issues': [], 'scope': 'aggregate_only'}
    if not isinstance(text, str) or len(text) > 20*1024*1024:
        return result
    tables = []
    for header in _HEADER.finditer(text):
        # Bound a table to the next section header or a modest block. Rows need
        # the exact model/count/token/cost shape, not arbitrary numeric text.
        end = min(len(text), header.end()+10000)
        next_header = _HEADER.search(text, header.end())
        if next_header:
            end = min(end, next_header.start())
        for row in _ROW.finditer(text, header.end(), end):
            fields = {k: _display(row.group(k), row.span(k), money=k.endswith('cost'), count=k == 'request_count')
                      for k in ('request_count', 'total_tokens', 'actual_cost', 'standard_cost')}
            if any(v is None for v in fields.values()):
                continue
            tables.append({'model': row.group('model'), 'request_count': int(fields.pop('request_count')['value']),
                           'fields': fields, 'evidence': [{'kind': 'model_summary_row', 'source_span': list(row.span())}]})
    cards = {}
    for field, label in _LABELS.items():
        pattern = re.compile(rf'(?<![\w]){label}\s*[:：]?\s*(?P<number>{_MONEY if field.endswith("cost") else _NUMBER})(?![\d.])', re.I)
        found = []
        for match in pattern.finditer(text):
            value = _display(match.group('number'), match.span('number'), money=field.endswith('cost'), count=field == 'request_count')
            if value:
                found.append(value)
        if found and all(_overlap(found[0], v) for v in found[1:]):
            cards[field] = found[0]
        elif found:
            result['issues'].append('conflicting_card_' + field)
    unique = []
    for row in tables:
        duplicate = next((old for old in unique if old['model'] == row['model'] and old['request_count'] == row['request_count']
                          and all(_overlap(old['fields'][k], v) for k, v in row['fields'].items())), None)
        if duplicate:
            duplicate['evidence'].extend(row['evidence'])
        else:
            unique.append(row)
    if cards.get('total_tokens') and cards.get('request_count'):
        card_count = int(cards.pop('request_count')['value'])
        compatible = [row for row in unique if row['request_count'] == card_count and
                      all(k not in row['fields'] or _overlap(row['fields'][k], v) for k, v in cards.items())]
        if len(unique) == 1 and len(compatible) == 1:
            # More precise displayed values may replace rounded table values.
            for k, v in cards.items():
                old = unique[0]['fields'].get(k)
                if old is None or v['upper']-v['lower'] < old['upper']-old['lower']:
                    unique[0]['fields'][k] = v
            unique[0]['evidence'].append({'kind': 'dashboard_cards', 'source_span': [0, len(text)]})
        elif not unique:
            unique.append({'model': None, 'request_count': card_count, 'fields': cards,
                           'evidence': [{'kind': 'dashboard_cards', 'source_span': [0, len(text)]}]})
        elif not compatible:
            result['issues'].append('cards_and_model_table_scope_differ')
    for row in unique:
        _infer_input(row['fields'], result['issues'])
    if unique:
        result['aggregates'] = unique
        result['status'] = 'recognized'
        models = [row['model'] for row in unique]
        if len(set(models)) != len(models) or result['issues']:
            result['status'] = 'ambiguous'
            result['issues'].append('conflicting_aggregates_do_not_sum')
    return result


def compare_summary(report, summary):
    """Compare aggregate claims only; time/key identity remains unverified."""
    result = {'status': 'not_comparable', 'scope': 'aggregate_only', 'scope_not_verified': True,
              'comparisons': [], 'note': '仅核对汇总数值；需属于同一测试 Key 和时间范围。汇总一致不证明真实上游用量，也不代表逐请求匹配。'}
    if not isinstance(report, dict) or not isinstance(summary, dict) or summary.get('status') != 'recognized':
        return result
    audit = report.get('token_audit') or summarize_report(report)
    totals = dict(audit.get('totals') or {})
    request_count = audit.get('request_count')
    model = report.get('model_requested') or report.get('target_model')
    # Deriving uncached input requires a known write count. With an omitted
    # write field retain the broader non-read figure with explicit semantics.
    if totals.get('input_tokens') is not None and totals.get('cache_read_tokens') is not None:
        write = totals.get('cache_write_tokens')
        totals['input_uncached_tokens'] = totals['input_tokens'] - totals['cache_read_tokens'] - (write or 0)
    statuses = []
    for aggregate in summary.get('aggregates', []):
        count_matches = aggregate.get('request_count') == request_count and request_count is not None
        model_matches = aggregate.get('model') == model if aggregate.get('model') else None
        row = {'model': aggregate.get('model'), 'request_count': aggregate.get('request_count'),
               'request_count_matches': count_matches, 'model_matches': model_matches, 'fields': {}}
        for field, displayed in aggregate.get('fields', {}).items():
            observed = totals.get(field)
            valid = type(observed) in (int, float) and math.isfinite(observed) and observed >= 0
            eligible = count_matches and model_matches is not False and valid
            status = 'not_comparable'
            if eligible:
                status = 'within_display_precision' if displayed['lower'] <= observed <= displayed['upper'] else 'different'
            detail = {'reported': observed, 'displayed': displayed, 'status': status}
            if field == 'input_uncached_tokens' and totals.get('cache_write_tokens') is None:
                detail['status'] = 'not_comparable'
                detail['note'] = '接口未提供缓存写入量；输入减缓存读取仅为非读取部分，不能认定为普通输入。'
            row['fields'][field] = detail
            statuses.append(detail['status'])
        result['comparisons'].append(row)
    if 'different' in statuses:
        result['status'] = 'aggregate_difference'
    elif 'within_display_precision' in statuses:
        result['status'] = 'within_display_precision'
    return result
