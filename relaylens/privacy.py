"""Explicit data minimization at the report boundary."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from typing import Any


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()
                if k.lower() not in {"api_key", "authorization", "cookie", "set-cookie", "proxy", "base_url", "x-api-key"}}
    if isinstance(value, list):
        return [redact(x, secrets) for x in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            for form in (secret, urllib.parse.quote(secret, safe=""),
                         base64.b64encode(secret.encode()).decode()):
                value = value.replace(form, "[REDACTED]")
    value = re.sub(r"\b(?:sk|sess)-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
    value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value)
    value = re.sub(r"https?://[^\s\"'<>]+", "[URL]", value)
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n\"'<>]+", "[LOCAL_PATH]", value)
    value = re.sub(r"/(?:home|Users|mnt/[a-z])/[^\s\"'<>]+", "[LOCAL_PATH]", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]", value)
    value = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b','[EMAIL]',value)
    return value


def private_report(report: dict, secrets: tuple[str, ...] = ()) -> dict:
    # Copy: scrubbing must not mutate the live conversation/tool context.
    result = redact(json.loads(json.dumps(report, ensure_ascii=False)), secrets)
    result.pop('egress',None)
    result.pop('network',None)
    # Billing identifiers and OCR text can disclose account/user information.
    # Public reports retain only aggregate measurements, never raw bills.
    if isinstance(result.get('billing'),dict):
        bill = result['billing']
        result['billing'] = {k:v for k,v in bill.items() if k in
            ('state','matched','coverage','total_requests','unmatched','ambiguous','fetch_state','import_state')
            and (v is None or isinstance(v,(bool,int,float)) or k in ('state','fetch_state','import_state'))}
    result.pop('billing_import',None)
    result.pop('billing_summary',None)
    if isinstance(result.get('token_audit'),dict): result['token_audit'].pop('requests',None)
    for comparison in result.get('token_reference_panel',{}).get('comparisons',[]): comparison.pop('pairs',None)
    result['model_requested'] = '[gateway alias removed]'
    if 'models' in result:
        result['models'] = {k:v for k,v in result['models'].items() if k in ('http_status','transport_state','latency_ms')}
    for row in result.get('cases',[]):
        # A custom suite or error response may contain names, private prompts,
        # arbitrary personal strings or addresses without a recognizable pattern.
        # Export structural measurements, not those free-text fields.
        for key in ('id','case_id'):
            if key in row and report.get('export_kind') != 'public_measurements':
                row[key] = hashlib.sha256(str(row[key]).encode()).hexdigest()
        observed = row.get('observed',{})
        row['observed'] = {k:v for k,v in observed.items() if k in ('http_status','transport_state','latency_ms',
                            'first_token_ms','payload_hash','completed','incomplete','reasoning_tokens')}
        if 'grade' in row:
            row['grade'] = {k:v for k,v in row['grade'].items() if k in ('passed','content_passed','format_passed','cases_passed','cases_total','content_policy','component_score')}
    if 'diagnostics' in result:
        result['diagnostics'].pop('returned_models',None)
        stability = result['diagnostics'].get('stability',{})
        if report.get('export_kind') != 'public_measurements':
            stability['pass_fail_flip_tasks'] = [hashlib.sha256(str(x).encode()).hexdigest() for x in stability.get('pass_fail_flip_tasks',[])]
    result['export_kind'] = 'public_measurements'
    return result
