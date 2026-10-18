# Hands-on OpenCode evidence at openkubes 8a5123b — 2026-10-18

This recorded hands-on run exercised OpenCode inference and tool execution with
`hostUsers: false` at openkubes `8a5123b`, after the separate 39/39 reconciler proof.
No commands were rerun to assemble this evidence.

## Revisions and cluster

| Repository | Commit used for the run |
| --- | --- |
| openkubes | `8a5123b` |
| ok-cluster | `751163d` |
| ok-storage | `e24edcb` |

The target was the same fresh disposable `ok-178-ws` cluster as
[`live-ok-178-ws-933f69ab290b2fd0.json`](../live-ok-178-ws-933f69ab290b2fd0.json)
(context `ok-178-ws-admin@ok-178-ws`). That JSON records
`target.kubeSystemUidSha256` as
`19441c3a433df529da25b96ac3da5fc7add4d24ec456add77bca752cc6cec5d4`.
The published step transcripts do not record that hash. The driver's own trace (not
published; it contains workstation paths) re-read the kube-system UID at 04:26:34Z,
before step 14, and its SHA-256 equals that value. The 39/39 JSON records
`finishedAt` 04:22:10Z; the driver started the hands-on flow at 04:22:10Z, with no
teardown in between.

The 39/39 JSON's `implementation.files` hashes, including the capability README,
describe `implementation.head` at `8a5123b` (full commit
`8a5123bd6c1933c4147e41b286d19198efab80b3`). They are a run-time record of that
revision. This PR's capability README text change is documentation only; the
39/39 JSON and the implementation and spike files remain unchanged.

## Recorded steps

Times below are UTC on 2026-10-18, taken with exit codes from the driver record.
The per-step logs contain command output; the driver recorded process exit codes
separately. Links preserve the original step names. OpenCode event timestamps in
`16-opencode.log` come from the workspace Pod's clock, which ran about 2 s ahead of
the driver's.

| Step / transcript | Driver start | Exit code | Recorded result |
| --- | --- | --- | --- |
| [12 alias create](12-alias-create.log) | 04:22:10Z | 0 | Manual `ok174-gpt-oss:20b` alias of `gpt-oss:20b`, context size 32768; alias listed. |
| [13 live-up](13-live-up.log) | 04:22:11Z | 0 | `ws-hands-on-xr`, Namespace `dw-hands-on`, runtime Pod `workspace-6f88c7d4f6-7sn4d`. |
| 14 userns, initial driver attempt | 04:24:18Z | 1 | Empty Pod name supplied by driver; see retry disclosure. |
| [14 userns, corrected retry](14-userns.log) | 04:26:35Z | 0 | `hostUsers=false`; `/proc/self/uid_map`: `0 242614272 65536`. |
| [15 verify before](15-verify-before.log) | Not recorded | 1 (expected) | Fixture has not yet been modified; verification fails. |
| [16 OpenCode two-call task](16-opencode.log) | 04:26:42Z | 0 | Both scripted bash tool calls completed with metadata `exit: 0`. |
| [17 verify after](17-verify-after.log) | 04:27:59Z | 0 | Verification succeeds; workspace status is ` M README.md`. |
| [18 live-down](18-live-down.log) | 04:28:01Z | 0 | Reports hands-on workspace, Namespace, PV, profile and fixture removed (or already absent). |
| [19 alias delete](19-alias-delete.log) | 04:30:01Z | 0 | Alias absent from the resulting model list; `gpt-oss:20b` remains. |
| [20 live-uninstall](20-live-uninstall.log) | 04:30:02Z | 0 | Crossplane release uninstalled; reports 21 Crossplane CRDs removed. |

The agent was explicitly instructed to make exactly two shell tool calls with
these commands, then report their exit codes. Steps 16 and 17 split the command
printed by `live-up` into separate OpenCode and verification execs.

```sh
printf '%s\n' 'developer workspace fixture modified by agent' > README.md
sh verify.sh
```

The structured OpenCode transcript records those two calls and both tool exits as
0. The independent before/after verification distinguishes the initial unmodified
fixture from the agent-modified fixture.

### Driver retry disclosure

The first step 14 attempt passed an empty Pod name and returned 1. The driver
record contains `== RESUME` markers at 04:25:55Z and 04:26:34Z. The empty Pod name
was a driver bug, not a workspace failure; the workspace was untouched. The driver
was then restarted: the first restart (04:25:55Z) exited before running any step,
and the second (04:26:34Z) reran step 14 onward. The corrected step 14
returned 0. The retained `14-userns.log` is the successful retry's output, not a
transcript of the failed attempt. The table discloses both attempts; the original
per-step log was overwritten by the retry.

## Transcript handling and integrity

Each `.log` is the corresponding recorded step transcript with shell-trace lines
starting `+ ` dropped, workstation checkout paths replaced with `<checkout>`, and
the inference endpoint address replaced with `<inference-endpoint>`. Nothing else
in those transcripts was changed. These inputs happen to contain the paths and
endpoint only in the dropped trace lines. Exit codes and timestamps above are
summarized from the separate driver record, which is not reproduced here.

`SHA256SUMS` covers all nine redacted transcripts and this README. Verify locally:

```sh
sha256sum -c SHA256SUMS
```

## Scope of this evidence

One task, one disposable cluster, one manual model alias. The agent made two
scripted tool calls. This exercises OpenCode inference and tool execution under
user namespaces once; it is not evidence of general agent capability, performance,
or production readiness. It does not test autonomous task selection, arbitrary
tasks, other models, other clusters, or sustained operation. The OpenCode
transcript does not name the model or endpoint; that requests reached the
`ok174-gpt-oss:20b` alias follows from the selected profile, not from these
transcripts. The model itself runs on the external inference host; only the
OpenCode client and its tool calls ran inside the `hostUsers: false` Pod.

`live-up` and `live-down` themselves write no evidence; these are retained operator
transcripts. `live-run` still does not rerun inference. The separate 39/39 JSON
retains its original scope and limits; these transcripts supplement it, without
turning its checks into an inference test or broadening its other claims.
