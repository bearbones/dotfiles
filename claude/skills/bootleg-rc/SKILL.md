---
name: bootleg-rc
description: Start a remote-control session via Slack. Creates a thread in your DM with yourself, then polls it for new messages and executes instructions. All agent messages are prefixed with "Agent says:" for easy visual distinction. Use /bootleg-rc to start, or /bootleg-rc stop to end the polling loop.
argument-hint: [stop]
---

# Bootleg Remote Control via Slack

Emulates remote-control over Slack by creating an RC thread in your self-DM and polling it for instructions.

## Architecture

1. **Setup phase**: Send an initial message to your self-DM, prefixed with "Agent says:"
2. **Polling phase**: Use a recurring `CronCreate` (every 2 min, session-only). A `UserPromptSubmit` hook (`~/.claude/hooks/bootleg-rc-gate.sh`) intercepts each cron firing and checks `next_poll_at` in the state file — if it's too early, it exits 2 to **block the LLM entirely** (zero tokens, zero cache cost). The LLM only wakes up when a Slack check is actually due.
3. **Execution phase**: When new user messages are found, execute the instructions and reply in-thread

The polling uses **exponential backoff** based on inactivity (no user messages in the thread):
- 0–10 min idle: check every 2 min
- 10+ min idle: interval doubles each cycle (2→4→8→16→32 min, capped at 30 min)
- 4 hours idle: session auto-terminates with a farewell message

## Constants

```
MY_SLACK_USER_ID       = "U06S3137VLN"
RC_POLL_CRON           = "*/2 * * * *"
BACKOFF_THRESHOLD_SECS = 600      # 10 min before backoff starts
BACKOFF_MAX_SECS       = 1800     # 30 min max interval
IDLE_STOP_SECS         = 14400    # 4 hours before auto-stop
INITIAL_INTERVAL_SECS  = 120      # 2 min starting interval
```

The DM channel ID is the user's own user ID (Slack uses user_id as channel_id for self-DMs).

---

## If argument is "stop"

End the RC session:
1. Call `CronList` to find any active cron jobs whose prompt contains `bootleg-rc-poll`
2. For each matching job, extract the state file path from its prompt (look for `State file for THIS session: /tmp/bootleg-rc-state-<...>.json`)
3. Call `CronDelete` on each matching job
4. Delete the associated state files: `rm -f /tmp/bootleg-rc-state-<thread_ts>.json`
5. Send a final message to the RC thread: "Agent says: RC session ended. Goodbye! 👋"
6. Report to the user that the RC session has been terminated

---

## Step 1: Create the RC Thread

Send a message to the self-DM (channel_id = `U06S3137VLN`) using `mcp__mcp-gateway-slack__slack_send_message`:

```
channel_id: "U06S3137VLN"
message: "Agent says: 🤖 **Remote Control session started**\n\nI'm monitoring this thread for instructions. Send messages here and I'll execute them.\n\n_Session started at <current time>_\n_Working directory: <cwd>_\n\nTip: I check every ~2 minutes initially. After 10 min of silence I'll back off; after 4 hours idle I'll shut down automatically."
```

**Capture the `message_ts`** from the response. Also capture the **message link** to show the user.

---

## Step 2: Store Initial State

Run `date +%s` via Bash to get current epoch as `NOW_EPOCH`.

```bash
cat > /tmp/bootleg-rc-state-<thread_ts>.json << 'EOF'
{
  "channel_id": "U06S3137VLN",
  "thread_ts": "<captured thread_ts>",
  "last_checked_ts": "<same as thread_ts initially>",
  "last_message_epoch": <NOW_EPOCH>,
  "next_poll_at": <NOW_EPOCH + 120>,
  "current_interval_secs": 120,
  "session_start": "<ISO timestamp>"
}
EOF
```

---

## Step 3: Set Up Polling

Create a session-only recurring cron. **Embed the full state file path** in the prompt so the hook and the poll handler both know which session to operate on:

```
CronCreate:
  cron: "*/2 * * * *"
  recurring: true
  durable: false
  prompt: |
    bootleg-rc-poll: Check for new messages in the Slack RC thread.
    
    State file for THIS session: /tmp/bootleg-rc-state-<thread_ts>.json
    
    (A UserPromptSubmit hook has already verified it's time to poll — no gate check needed here.)
    
    ## Step 1: Read state
    Read /tmp/bootleg-rc-state-<thread_ts>.json.
    Run `date +%s` via Bash to get NOW.
    
    ## Step 2: Check for new messages
    Use mcp__mcp-gateway-slack__slack_read_thread with:
      - channel_id from state
      - message_ts (thread parent) = thread_ts from state
      - oldest: last_checked_ts
    Filter out messages starting with "Agent says:" — those are mine.
    Call the remaining messages NEW_MESSAGES.
    
    ## Step 3a: If NEW_MESSAGES is non-empty
    For each message:
      a. Execute the instruction
      b. Reply in-thread prefixed with "Agent says:" using mcp__mcp-gateway-slack__slack_send_message
    Set last_checked_ts = timestamp of newest message processed.
    Set last_message_epoch = NOW.
    Set current_interval_secs = 120.   ← reset to fast polling after activity
    
    ## Step 3b: If NEW_MESSAGES is empty
    Calculate INACTIVITY = NOW - last_message_epoch.
    
    If INACTIVITY >= 14400 (4 hours):
      Send to thread: "Agent says: 🔇 No activity for 4 hours — shutting down automatically. Use /bootleg-rc to restart."
      Run `rm -f /tmp/bootleg-rc-state-<thread_ts>.json` via Bash.
      Stop. Do not update state.
    
    Else if INACTIVITY >= 600 (10 min):
      Set current_interval_secs = min(current_interval_secs * 2, 1800).
    
    ## Step 4: Update state
    Set next_poll_at = NOW + current_interval_secs.
    Write updated state back to /tmp/bootleg-rc-state-<thread_ts>.json.
    
    IMPORTANT:
    - Always prefix Slack replies with "Agent says: "
    - Keep replies concise but informative
    - If an instruction is ambiguous, ask for clarification rather than guessing
    - If an instruction would be destructive (git push --force, rm -rf, etc.), ask for confirmation
    - For long-running operations, reply immediately that you're working on it, then reply again with results
```

---

## Step 4: Report to User

```
RC session started! 🤖

Thread: <message_link>
Polling: every ~2 min initially; backs off to 30 min after 10 min of inactivity; auto-stops after 4 hours idle
Idle cost: zero — a hook blocks LLM invocation when it's too early to check Slack
Channel: Your self-DM

Send messages in that thread and I'll pick them up on the next poll cycle.
To stop: /bootleg-rc stop
```

---

## Notes

- **Hook gating**: `~/.claude/hooks/bootleg-rc-gate.sh` (a `UserPromptSubmit` hook) runs in pure bash before any LLM context loads. It reads `next_poll_at` from the state file and exits 2 (block) if it's too early — zero tokens, zero cache cost for idle polls.
- The cron stays simple (recurring every 2 min); all backoff logic lives in the poll handler updating `next_poll_at`.
- Exponential backoff: interval doubles after 10 min of inactivity (2→4→8→16→32 min, max 30 min).
- Activity resets `current_interval_secs` to 120 for fast response.
- After 4 hours idle: sends farewell, deletes state file — hook will pass through next time and the poll handler will find no state file and exit cleanly.
- State lives in `/tmp/bootleg-rc-state-<thread_ts>.json` — namespaced by session to avoid collisions.
- Cron is session-only (`durable: false`) — dies when this Claude Code session ends.
