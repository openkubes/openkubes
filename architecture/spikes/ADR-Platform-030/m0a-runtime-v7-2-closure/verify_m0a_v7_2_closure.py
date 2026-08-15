#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
from typing import Any
import yaml
class VerificationError(ValueError):pass
def sha(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def expect(actual:Any,expected:Any,claim:str)->None:
    if actual!=expected:raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")
def verify(path:Path)->str:
    s=yaml.safe_load(path.read_text())["spec"]
    expect(s["state"],"CAAPH-CONTROL-PLANE-READY","state")
    expect(s["repair"]["patchResult"],"SUCCESS","patch")
    expect(s["repair"]["runsConsumed"],1,"runs")
    expect(s["repair"]["historicalEvaluatorResult"],"STOP-NOT-SUCCESS","historical result")
    expect(s["correctedEvaluation"]["result"],"PASS","corrected result")
    expect(s["correctedEvaluation"]["mutationPerformed"],False,"evaluation mutation")
    expect(s["readiness"],{"reviewedObjectsPresent":19,"deploymentAvailable":True,"deploymentGeneration":2,"deploymentObservedGeneration":2,"readyControllerPods":1,"controllerRestarts":0,"certificateReady":True,"crdsEstablished":2,"serviceEndpointsReady":2},"readiness")
    expect(s["imageIdentity"]["runtimeImageIDEqualsLockedIndex"],True,"runtime index")
    expect(s["imageIdentity"]["runtimeImageIDEqualsPlatformChild"],False,"runtime platform claim")
    expect(s["zeroTargetBoundary"],{"helmChartProxies":0,"helmReleaseProxies":0,"capiClusters":0,"capiMachines":0,"capiMachineDeployments":0,"targetConvergencePerformed":False},"zero target")
    expect(s["conclusion"]["caaphControlPlaneReady"],True,"conclusion")
    expect(s["conclusion"]["repairGrantReusable"],False,"grant reuse")
    for k,v in s["authorization"].items():expect(v,False,k)
    for k,v in s["redaction"].items():expect(v,False,k)
    return sha(path)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--evidence",type=Path,required=True);a=p.parse_args()
    try:print(verify(a.evidence.resolve()));return 0
    except (OSError,KeyError,TypeError,ValueError,VerificationError,yaml.YAMLError) as e:print(f"ERROR: {e}");return 2
if __name__=="__main__":raise SystemExit(main())
