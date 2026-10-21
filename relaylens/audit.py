"""Run a compact, reproducible black-box audit against one compatible API."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import random
import time
from pathlib import Path

from .privacy import private_report
from .stats import summary
from .stats import paired
from .model_targets import TARGET_CHOICES, profile
from .suite_loader import load_suite
from .transport import Client, extract

EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def make_tool_case(seed: int):
    """Create a per-run tool schema so providers cannot key on one fixed name."""
    rng = random.Random(seed ^ 0x5EEDC0DE)
    name = f"lookup_{rng.getrandbits(32):08x}"
    city, temperature, condition = rng.choice((
        ("Paris", 17, "clear"),
        ("Osaka", 23, "humid"),
        ("Quito", 14, "cloudy"),
        ("Reykjavik", 6, "windy"),
    ))
    tool = {"type":"function", "name":name,
            "description":"Return the temperature and short condition for a city.",
            "parameters":{"type":"object", "properties":{"city":{"type":"string"}},
                          "required":["city"], "additionalProperties":False}, "strict":True}
    prompt = f"Call {name} for {city}, then use its result to answer the user."
    result = {"city":city, "temperature_c":temperature, "condition":condition}
    return tool, prompt, result


def verdict(report):
    """Conservative user-facing labels; labels describe evidence, never identity."""
    model_listed = report.get("model_requested") in report.get("models",{}).get("ids",[])
    completed = [x for x in report.get("cases",[]) if x.get("completed")]
    graded = [x for x in completed if "grade" in x]
    passed = sum(bool(x["grade"].get("passed")) for x in graded)
    task_rate = passed/len(graded) if graded else None
    tool = report.get("tool_summary",{})
    failed_parameters = [x for x in report.get("cases",[]) if x.get("family")=="parameter" and not x.get("completed")]
    if report.get("models",{}).get("transport_state") != "ok" or not model_listed or not completed:
        return {"grade":"D","label":"接口不可用、未认证或目标模型未列出","identity_claim":"not established","reasons":["Missing a usable catalog or successful response; this is not an identity proof."]}
    if len(failed_parameters) > len([x for x in report.get("cases",[]) if x.get("family")=="parameter"])/2 or (task_rate is not None and task_rate < .5) or not (tool.get("call_detected") and tool.get("followup_completed") and tool.get("result_used")):
        return {"grade":"C","label":"存在明显协议或任务行为不一致","identity_claim":"mismatch evidence","reasons":["At least one independent capability layer failed; inspect raw cases and errors."]}
    comparison=report.get("reference_comparison",{}).get("paired",{})
    if comparison.get("n_cases",0)>0 and comparison.get("bootstrap_95") and comparison["bootstrap_95"][0] <= 0 <= comparison["bootstrap_95"][1]:
        return {"grade":"A","label":"与参考端点在本测试套件中行为接近","identity_claim":"behavioral similarity only","reasons":["A paired interval includes no observed pass-rate difference; this does not prove shared weights."]}
    return {"grade":"B","label":"接口和任务表现通过，但缺少足够的参考证据","identity_claim":"inconclusive","reasons":["A single gateway can imitate names and schemas or change upstream routing."]}


def run(args):
    if not args.api_key:
        args.api_key = os.environ.get("RELAYLENS_API_KEY") or getpass.getpass("API key (hidden): ").strip()
    suite_fn, suite_version, suite_source, suite_commitment = load_suite(args.suite_module)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 2**63)
    client = Client(args.base_url,args.api_key,api=args.api,route=args.route,proxy=args.proxy,
                    timeout=args.timeout,max_tokens=args.max_output_tokens)
    target = profile(args.target_model)
    report={"schema_version":"0.4","suite_version":suite_version,"suite_source":suite_source,
            "suite_commitment":suite_commitment,"started_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
            "base_url":client.base,"api_style":args.api,"model_requested":args.model,
            "target_model":args.target_model,"target":target,"seed":seed,
            "network":{"route":args.route,"proxy_configured":bool(args.proxy)},"cases":[]}

    def add(case_id,family,prompt,call,task=None):
        observed,calls,context=extract(call,args.api)
        row={"id":case_id,"case_id":case_id,"family":family,"prompt_hash":task.prompt_hash if task else None,
             "completed":observed["completed"],"observed":observed}
        if task: row["grade"]=task.grade(observed.get("text",""))
        report["cases"].append(row)
        return observed,calls,context

    models=client.request("/models")
    report["models"]={"http_status":models.get("http_status"),"transport_state":models.get("transport_state"),
                       "latency_ms":models.get("latency_ms"),"error":models.get("error"),
                       "ids":[x.get("id") for x in (models.get("data") or {}).get("data",[]) if isinstance(x,dict)]}
    for effort in args.efforts:
        call=client.call(args.model,"Reply with exactly the token RELAYLENS_OK.",effort=effort,stream=args.stream)
        observed,_,_=add("parameter-"+effort,"parameter","",call)
        observed["requested_effort"]=effort
    if args.task_rounds:
        for task in suite_fn(seed,args.task_rounds):
            call=client.call(args.model,task.prompt,effort=args.task_effort,stream=args.stream)
            add(task.id,task.family,task.prompt,call,task)

    tool, tool_prompt, tool_result = make_tool_case(seed)
    call=client.call(args.model,tool_prompt,tools=[tool],effort=args.task_effort,stream=False)
    observed,calls,context=add("tool-initial","tool", "",call)
    if calls:
        if args.api == "responses":
            follow_context=(context or []) + [{"type":"function_call_output","call_id":calls[0].get("call_id"),"output":json.dumps(tool_result)}]
        else:
            follow_context=[context, {"role":"tool","tool_call_id":calls[0].get("call_id"),"content":json.dumps(tool_result)}]
        follow=client.call(args.model,None,context=follow_context,tools=[tool],effort=args.task_effort,stream=args.stream)
        observed2,_,_=add("tool-followup","tool_followup", "",follow)
        observed["tool_call_detected"]=True
        observed["tool_followup_completed"]=observed2["completed"]
        follow_text=(observed2.get("text") or "").lower()
        observed["tool_result_used"]=any(str(value).lower() in follow_text for value in (tool_result["temperature_c"], tool_result["city"], tool_result["condition"]))
    else:
        observed["tool_call_detected"]=False; observed["tool_followup_completed"]=False; observed["tool_result_used"]=False
    report["task_summary"]=summary(report["cases"])
    report["tool_summary"]={"call_detected":bool(observed.get("tool_call_detected")),"followup_completed":bool(observed.get("tool_followup_completed")),"result_used":bool(observed.get("tool_result_used"))}
    report["verdict"]=verdict(report)
    report["client_environment"]={"python_major_minor":".".join(platform.python_version().split(".")[:2]),"platform":"generic"}
    report["privacy_note"]="Raw prompts, API keys, authorization headers, full URLs, local paths and IPs are omitted from this report."
    return report


def main(argv=None):
    p=argparse.ArgumentParser(prog="relaylens",description="Reproducible black-box audit for OpenAI-compatible model gateways")
    p.add_argument("--base-url",required=True); p.add_argument("--model",required=True); p.add_argument("--api-key")
    p.add_argument("--target-model", choices=TARGET_CHOICES,
                   help="claimed GPT or Claude model; reports the claim separately from observed behavior")
    p.add_argument("--api",choices=("responses","chat"),default="responses"); p.add_argument("--route",choices=("env","direct"),default="env"); p.add_argument("--proxy")
    p.add_argument("--seed",type=int); p.add_argument("--task-rounds",type=int,default=3); p.add_argument("--task-effort",default="high",choices=EFFORTS)
    p.add_argument("--suite-module", help="optional private Python suite defining suite(seed, rounds)")
    p.add_argument("--efforts",nargs="+",default=list(EFFORTS),choices=EFFORTS); p.add_argument("--stream",action="store_true")
    p.add_argument("--timeout",type=float,default=60); p.add_argument("--max-output-tokens",type=int,default=1200)
    p.add_argument("--out",default="relaylens-report.json"); p.add_argument("--public-out",help="write a scrubbed shareable report")
    p.add_argument("--reference-report",help="same-suite reference JSON for paired case comparison")
    args=p.parse_args(argv)
    report=run(args)
    if args.reference_report:
        try:
            reference=json.loads(Path(args.reference_report).read_text(encoding="utf-8"))
            compatible = {k: report.get(k) == reference.get(k) for k in ("suite_version","suite_commitment","seed","api_style")}
            report["reference_comparison"]={"compatible":compatible,"paired":paired(report["cases"],reference.get("cases",[]),seed=report["seed"])}
            report["verdict"]=verdict(report)
        except Exception as exc:
            report["reference_comparison"]={"error":f"{type(exc).__name__}: {exc}"}
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.public_out:
        Path(args.public_out).write_text(json.dumps(private_report(report,(args.api_key or "",)),ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"report":str(Path(args.out).resolve()),"public_report":str(Path(args.public_out).resolve()) if args.public_out else None,
                      "verdict":report.get("verdict"),"model_listed":args.model in report["models"].get("ids",[]),
                      "target_model":report.get("target_model"),"target_family":(report.get("target") or {}).get("family"),
                      "task_summary":report.get("task_summary"),"tool_summary":report["tool_summary"]},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
