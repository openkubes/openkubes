from __future__ import annotations
import copy,os,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import controlled_m0a_execution_v7_1 as module
CANDIDATE=ROOT/"m0a-execution-candidate-v7-1.yaml"
class Tests(unittest.TestCase):
    def grant(self,directory:Path)->Path:
        now=datetime.now(timezone.utc);v={"spec":{"version":"ok141-m0a-combined-grant/v7.1","candidateDigest":module.sha(CANDIDATE),"authority":"github:arashkaffamanesh","decision":"GO","mutationAuthorized":True,"administratorPrerequisiteGrant":{"gate":"M0A-AP1-v7.1","granted":True,"grantID":"ap"},"credentialGrant":{"gate":"M0A-C1-v7.1","granted":True,"grantID":"c"},"admissionGrant":{"gate":"M0A-A1-v7.1","granted":True,"grantID":"a"},"installationGrant":{"gate":"M0a-I-v7.1","granted":True,"grantID":"i"},"validFrom":(now-timedelta(minutes=1)).isoformat(),"validUntil":(now+timedelta(minutes=1)).isoformat(),"maximumRuns":1,"evidenceOutputPath":"/private/tmp/ok141-v71-test.json","retryGranted":False,"rollbackGranted":False,"targetConvergenceGranted":False,"m0bInstallationGranted":False,"go1Granted":False,"evidencePublicationGranted":False,"failureInjectionGranted":False}}
        p=directory/"grant.yaml";p.write_text(yaml.safe_dump(v,sort_keys=False));return p
    def test_candidate_is_no_go_and_verifies(self):
        c,_,_,_=module.verify_candidate(CANDIDATE);self.assertFalse(c["spec"]["authorization"]["mutationAuthorized"])
        self.assertEqual(module.sha(CANDIDATE),(ROOT/"m0a-execution-candidate-v7-1.sha256").read_text().strip())
    def test_exact_four_grants_verify_offline(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(module.verify_grant(CANDIDATE,self.grant(Path(d)))["maximumRuns"],1)
    def test_duplicate_grant_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.grant(Path(d));v=yaml.safe_load(p.read_text());v["spec"]["installationGrant"]["grantID"]="a";p.write_text(yaml.safe_dump(v,sort_keys=False))
            with self.assertRaisesRegex(module.ExecutionError,"four distinct"):module.verify_grant(CANDIDATE,p)
    def test_template_is_no_go(self):
        s=yaml.safe_load((ROOT/"m0a-combined-grant-v7-1.template.yaml").read_text())["spec"];self.assertEqual(s["candidateDigest"],module.sha(CANDIDATE));self.assertEqual(s["decision"],"NO-GO");self.assertFalse(s["mutationAuthorized"])
    def test_raw_evidence_is_exclusive_and_mode_0600(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"evidence.json";module.write_evidence(p,{"redacted":False});self.assertEqual(os.stat(p).st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):module.write_evidence(p,{"second":True})
if __name__=="__main__":unittest.main()
