#!/usr/bin/env python3
import argparse,hashlib,json,sys
from pathlib import Path
import yaml
class ClosureError(ValueError): pass
def digest(p): return "sha256:"+hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(v): return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def verify(path):
    value=yaml.safe_load(Path(path).read_text()); spec=value.get("spec",{}) if isinstance(value,dict) else {}; errors=[]
    if spec.get("state")!="PASS-D3-CAPI-CLUSTER-ABSENT-REDACTED": errors.append("state mismatch")
    result=spec.get("result",{})
    for k in ("clusterDeleteRequested","clusterAbsent","foregroundPropagationUsed"):
        if result.get(k) is not True: errors.append(f"{k} not proven")
    for k in ("childDeleteRequestedByRunner","providerSecretDeleteRequested","retryPerformed","rollbackPerformed","cleanupPerformed","forceDeletePerformed","finalizerMutationPerformed"):
        if result.get(k) is not False: errors.append(f"{k} boundary mismatch")
    if spec.get("conclusion")!={"detailedControllerGraphClosureProven":False,"d4Required":True}: errors.append("D4 boundary mismatch")
    if any(v is not False for v in spec.get("redaction",{}).values()): errors.append("redaction mismatch")
    auth=spec.get("authorization",{})
    if auth.get("decision")!="NO-GO" or any(v is not False for k,v in auth.items() if k.endswith("Granted")): errors.append("closure grants authority")
    if errors: raise ClosureError("; ".join(errors))
    return value
def main():
    p=argparse.ArgumentParser(); p.add_argument("--closure",type=Path,required=True); a=p.parse_args(); v=verify(a.closure); print(json.dumps({"closureDigest":digest(a.closure),"semanticDigest":canonical(v),"state":"PASS-D3-CLOSURE-REDACTED-NO-GO"},sort_keys=True))
if __name__=="__main__":
    try: main()
    except (ClosureError,OSError,ValueError) as e: print(f"ERROR: {e}",file=sys.stderr); raise SystemExit(1)
