---
name: ps5-failure-triage
description: Analyze PS5 unit test failures from TeamCity CI, cluster them into root-cause categories, and create or update Jira tickets under TEXT-205. Use when the user asks to triage PS5 failures, check PS5 CI, or analyze PS5 test results.
tools: Bash, Read, Glob, Grep
---

# PS5 Failure Triage

Analyzes the latest PS5 unit test build in TeamCity, clusters failures by root cause, and creates or updates Jira tickets under the TEXT-205 epic.

## Context

- **Build configuration**: `Client_Migration_Integration_CbTCmake_Playstation_PlaystationBuilds_CommonTestsPs5unitTests`
- **Jira epic**: [TEXT-205](https://roblox.atlassian.net/browse/TEXT-205) — Playstation CI Testing
- **Aggregator story**: [TEXT-550](https://roblox.atlassian.net/browse/TEXT-550) — PS5 CI: Pre-existing test failures — root cause analysis
  - All new tickets should be **linked to TEXT-550 as "relates to"**
  - After analysis, add a comment to TEXT-550 summarizing the session's findings

## Tools

All tool paths assume the working directory is `~/git/roblox/game-engine/`.

```bash
# TeamCity
TC=".claude/skills/teamcity/scripts/tc"

# Jira
JIRA="Tools/Util/gobot uv run --project .claude .claude/skills/jira-integration/scripts/jira_cli.py"
```

## Workflow

### Step 1 — Find the latest builds

```bash
$TC builds Client_Migration_Integration_CbTCmake_Playstation_PlaystationBuilds_CommonTestsPs5unitTests --count 5
```

Pick the **most recent completed build** (status SUCCESS or FAILURE — not running). Note its build ID.

Also note the build ID of the **previous run** for comparison (helps distinguish new regressions from pre-existing failures).

### Step 2 — Get failing tests

```bash
$TC tests-count <build-id> --status FAILURE
$TC tests <build-id> --status FAILURE --details
```

If the count is 0, note that the build was clean and stop — no tickets needed.

Capture the full test names and failure messages. Each test result has:
- **Test name**: usually `SuiteName/TestName` or `ClassName.TestName`
- **Failure details**: the assertion or exception that triggered the failure

### Step 3 — Cluster failures

Group failing tests into root-cause categories. Use the **existing ticket categories as your primary clustering guide** (see reference section below). For each test:

1. Check if the test name or failure message matches a known category — assign it there.
2. If no existing category fits, propose a new cluster. Name it with an ALL_CAPS category key (e.g., `CURSOR_INPUT_DIFFERENCES`).

A cluster should contain tests that share a **single underlying root cause**, not just a vague similarity. For example, "all network tests fail" is too broad; "UDP loopback never receives packets in RakNet socket descriptor path" is a cluster.

**Minimum cluster size**: 1 is fine if the failure is clearly distinct and important. Don't force small unique failures into wrong buckets.

### Step 4 — Compare against previous run (optional but valuable)

If you noted the previous build ID in Step 1:

```bash
$TC tests-count <prev-build-id> --status FAILURE
```

Flag which clusters are **new regressions** (not in prior run) vs **pre-existing failures**. This determines ticket priority.

### Step 5 — Search for existing Jira tickets

For each cluster, search for an existing open ticket:

```bash
$JIRA search 'project = TEXT AND summary ~ "PS5 CI" AND summary ~ "<key words from category>" AND statusCategory != Done' --limit 5
```

Use 2–3 distinctive words from the category (component name, root cause keyword). Review results — pick a match only if the ticket clearly covers the same root cause.

**If a match is found**: add a comment to the existing ticket with the new build data (build ID, test count, any new tests in the category, whether it's regressing or stable).

**If no match**: create a new ticket (Step 6).

### Step 6 — Create new tickets

For each cluster without an existing ticket:

```bash
$JIRA create \
  --project TEXT \
  --type Story \
  --summary "PS5 CI: <Component> — <root cause description>" \
  --description "<see template below>" \
  --epic TEXT-205
```

The `link` command is not available in jira_cli.py. Instead, note the relationship in the TEXT-550 summary comment (Step 7) — list all new tickets in the session summary table rather than formal issue links.

#### Ticket description template

```
h2. Overview

<1–2 sentences describing the failure and root cause.>

h2. Failing tests

||*Test name*||*Failure message (excerpt)*||
|<test.name>|<short failure excerpt>|
...

h2. Root cause hypothesis

<What is likely causing this? Platform limitation, missing stub, config difference, etc.>

h2. Recommended fix

<Test guard / platform skip / bug to investigate — be specific.>

h2. Reference

* TeamCity build: <full URL>
```

**Title format**: `PS5 CI: <Component/Test area> — <root cause in plain English>`

Examples of good titles (following existing pattern):
- `PS5 CI: Luau CodeAllocator tests fail — PS5 prohibits JIT executable memory (mmap PROT_EXEC)`
- `PS5 CI: RakNet packing/capability tests fail — UDP loopback packets never received`

### Step 7 — Comment on TEXT-550

After processing all clusters, add a summary comment to TEXT-550:

```bash
$JIRA comment TEXT-550 "
h2. Triage session — <DATE>

Build analyzed: [<build-id>|<full TC URL>]

h3. Results

* Total failures: <N>
* Clusters identified: <M>
* New regressions: <list or "none">

h3. Tickets updated/created

||*Ticket*||*Category*||*Count*||*Action*||
|TEXT-XXX|CATEGORY_KEY|N|updated / created|
...
"
```

## Known Categories (reference)

Use these when matching failures in Step 3. Each row shows the Jira ticket, category key, and what to look for in test names/errors.

| Ticket | Category key | Tests / signatures |
|--------|--------------|--------------------|
| TEXT-551 | `JIT_EXECUTABLE_MEMORY` | `Luau.*CodeAllocator`, `mmap.*PROT_EXEC`, null allocator |
| TEXT-552 | `MAPPED_FILE_UNSUPPORTED` | `MappedFile`, `asserts false` in `MappedFileUnsupported.cpp` |
| TEXT-553 | `SQLITE_FILESYSTEM` | `SQLITE_BUSY`, `rc=5`, `database is locked` |
| TEXT-554 | `RAKNET_UDP_LOOPBACK` | `RakNet.*Packing`, `RakNet.*Capability`, UDP peer fixture, no packets received |
| TEXT-555 | `SYSPOLLER_UDP` | `SysPoller`, `AggregatingPoller`, UDP socket creation fails |
| TEXT-556 | `STORAGE_ASYNC_TIMEOUT` | `SessionTracking`, `RbxStorage`, async hang |
| TEXT-557 | `HTTP_BIND_FAILURE` | local HTTP server bind, DataModel server bind |
| TEXT-558 | `REPLICATOR_TIMEOUT` | `Replicator`, `SharedStringSynchronizer`, 30s timeout |
| TEXT-559 | `NETWORK_REPLICATION_DATA` | terrain LOD mismatch, `MegaReplicator` assertion |
| TEXT-560 | `PROCESS_CRASH_SIGUSR2` | SIGUSR2 exit code -12, `AuroraScript`, batched join |
| TEXT-561 | `TEXTCHAT_SENDDATA` | `TextChat`, `Error: SendData:` after clients connect |
| TEXT-562 | `VOICE_WEBRTC_TURN` | Voice `WebRTC`, TURN connection event never fired |
| TEXT-563 | `HARMONY_UNINITIALIZED` | `copiedStates[id].enabled = false`, `CoordinatorV2`, `PlaylistSelector`, `RvCache` |
| TEXT-564 | `PHYSICS_SLEEP_CONVERGENCE` | physics assembly sleep state, step count |
| TEXT-565 | `MISSING_FEATURE_FLAGS` | `AnimatorRetargetR15_4`, `AnimatorAndADFRefactorInternal` not registered |
| TEXT-566 | `FMOD_AUDIO` | FMOD cannot load `.mp3`, audio scheduler timer precision |
| TEXT-567 | `FUNCTION_CURVE_TOLERANCE` | `FunctionCurveTest`, exponential curve, 0.01f tolerance |
| TEXT-568 | `ANIMATION_JOINT_ZERO` | `AnimationTrackEndToEndTest`, joint transforms return zero/identity |
| TEXT-569 | `TEST_ASSET_MISSING` | video resource HTTP 500, unexpected asset state |
| TEXT-570 | `HTTP_OUTBOUND_BLOCKED` | `PlayerHydrationService`, outgoing HTTP blocked |
| TEXT-571 | `RBXTEST_SLOW_STARTUP` | `.rbxl` tests, 75–80s PS5 startup, 120s budget |
| TEXT-572 | `PHYSICS_CONSTRAINT_TOLERANCE` | constraint solver, error vs tolerance |
| TEXT-573 | `CLONE_LINKED_SCRIPT_TIMEOUT` | `CloneLinkedScript`, 5s internal deadline |
| TEXT-581 | `VIDEO_STREAM_NOT_SUPPORTED` | `VideoThumbnailGeneratorTest`, `VideoStreamTest`, AppCore/Service.h assertion, format support misreported |
| TEXT-582 | `NETWORK_STREAMING_CORRECTNESS` | `ReplicatorStreamJobV2Test`, `StreamingIntegrityModeV2Test`, region queue not draining, pause event misfires |
| TEXT-583 | `CORE_SCRIPT_SYNC_SERVICE` | `CoreScriptSyncServiceTest`, `getInstanceByFilePath` returns wrong pointer |
| TEXT-584 | `RM3_SAFETY_CONFIG` | `RM3Tier0ConfigRefreshTest`, traceId mismatch, `visualFilterCfg.cadenceSec` missing |
| TEXT-585 | `WRAP_DEFORMER_MEMORY` | `WrapDeformerTest`, `wrap/layeredDeformer` memory category delta 220272→0 |
| TEXT-586 | `AVATAR_EDITOR_CRASH` | `AvatarEditorServiceTest`, `St12system_error invalid argument`, exit code 244 |
| TEXT-587 | `PHYSICS_CHARACTER_MOVEMENT` | `GroundControllerMovementTest.rbxl`, `PhysicsQuickTests.Dual/NotGoodForPrimal_MustResolveASAP` |
| TEXT-588 | `CONTENT_PROVIDER_HANG` | `ContentProviderTest`, `ModerationPendingMeshInvalidationScheduled`, 30s timeout |

## Step 8 — Add exclusions and open a PR

For **every cluster that has a Jira ticket** (new or existing), check whether its tests are already listed in `Client/BuildScripts/rotest/filter_config/ps5-exclusions.json`. If any tests are missing from the file, add a new rule (or extend an existing one) and open a PR.

### Exclusions file format

```json
{
  "version": 1,
  "rules": [
    {
      "tests": [
        "SuiteName/TestCaseName",
        "SuiteName/AnotherTest"
      ],
      "action": "exclude",
      "reason": "TEXT-NNN short description matching ticket summary",
      "conditions": {
        "platform": ["prospero-playstation"]
      }
    }
  ]
}
```

Rules:
- Use the exact test name as reported by TeamCity (`tc tests`), which is typically `SuiteName/TestCaseName`.
- One rule per cluster (same Jira ticket). If a rule already exists for the ticket, add the new tests to its `tests` array rather than creating a duplicate rule.
- The `reason` field must begin with the Jira ticket ID: `TEXT-NNN <short description>`.
- Always use `"action": "exclude"` and `"conditions": { "platform": ["prospero-playstation"] }`.

### Opening the PR

After editing the file, use the `rbx-create-pr` skill to create the PR. The PR title should follow the format:

```
TEXT-518 #nonprod ps5-exclusions: add <N> tests across <M> categories
```

Use TEXT-518 (quarantine PS5 failing tests) as the Jira ticket for the exclusions PR, since that is the umbrella task for quarantining failures.

The PR description should include:
- A table of categories and test counts added
- Links to the TeamCity build analyzed
- Links to each Jira ticket cited in the new rules

## Output

At the end of each session, report to the user:

1. Build ID analyzed and its date
2. Total failure count
3. Table of clusters: category, test count, ticket (updated or new), whether it's a new regression
4. How many tests were added to ps5-exclusions.json (or "all already present")
5. PR link (or "no new exclusions needed")
6. Any uncategorized tests that didn't fit existing clusters (list them — these may need new tickets)
