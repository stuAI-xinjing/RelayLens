"""Descriptive uncertainty and paired, case-clustered bootstrap comparisons."""
import math
import random
from collections import defaultdict


def wilson(passed, total, z=1.959963984540054):
    if total == 0: return None
    p=passed/total; denom=1+z*z/total
    center=(p+z*z/(2*total))/denom
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denom
    return [max(0.0,center-half),min(1.0,center+half)]


def summary(rows):
    groups = defaultdict(list)
    for row in rows:
        if "grade" in row: groups[row["family"]].append(row)
    out={}
    for family, items in sorted(groups.items()):
        completed=[x for x in items if x.get("completed")]
        passed=sum(bool(x["grade"].get("passed")) for x in completed)
        out[family]={"planned":len(items),"completed":len(completed),"passed":passed,
                     "accuracy":passed/len(items) if items else None,
                     "completed_accuracy":passed/len(completed) if completed else None,
                     "wilson_95":wilson(passed,len(items)),
                     "format_passed":sum(bool(x["grade"].get("format_passed")) for x in completed)}
    return out


def paired(candidate, reference, seed=0, samples=2000):
    refs={x["id"]:x for x in reference if "grade" in x}
    diffs=defaultdict(list); mismatches=[]
    for row in candidate:
        if "grade" not in row: continue
        ref=refs.get(row["id"])
        if ref is None or row.get("prompt_hash") != ref.get("prompt_hash"):
            mismatches.append(row["id"]); continue
        if row.get("completed") and ref.get("completed"):
            diffs[row["case_id"]].append(int(ref["grade"]["passed"])-int(row["grade"]["passed"]))
    values=[sum(v)/len(v) for v in diffs.values()]
    if not values: return {"n_cases":0,"mismatches":mismatches,"loss":None,"bootstrap_95":None}
    rng=random.Random(seed)
    boot=sorted(sum(rng.choice(values) for _ in values)/len(values) for _ in range(samples))
    return {"n_cases":len(values),"mismatches":mismatches,"loss":sum(values)/len(values),
            "bootstrap_95":[boot[int(samples*.025)],boot[min(samples-1,int(samples*.975))]],
            "method":"paired case-cluster bootstrap (descriptive; not identity probability)",
            "bootstrap_samples":samples}
