# How work flows through the factory

Two views of the same loop: a **flowchart** of the work-order lifecycle
(who may do what), and a **sequence diagram** of one full day/night cycle.

## Flowchart — the work-order lifecycle

```mermaid
flowchart TD
    subgraph DAY ["☀️ Day shift — people decide"]
        A["write order\n(status: draft)"] --> B["lint-order.py"]
        B -->|"problems"| B2["fix the order"]
        B2 --> B
        B -->|"clean"| C["status: approved + commit\nthis is the handover"]
        M["morning: status.py"] --> N{"verdict"}
        N -->|"good"| O["accept.py NNN\nsquash-merge into target main"]
        O --> P["done — push the target\n(factory never pushes)"]
        N -->|"not there yet"| Q["status: blocked\n+ question under Day shift decisions"]
        Q --> RE["re-approve for tonight\n(rerun resumes the session)"]
        N -->|"wrong direction"| R["rejected, with a reason"]
    end

    subgraph NIGHT ["🌙 Night shift — agents execute"]
        S["01:17 cron fires\nrun.py --max-orders 3"] --> T{"approved orders?"}
        T -->|"none"| U["log the no-op\nexit 0 — zero tokens"]
        T -->|"yes"| V["lint gate"]
        V -->|"malformed"| W["blocked — no tokens spent\nhealthy orders still run"]
        V -->|"clean"| X["throwaway worktree\nbranch wo/NNN from local main"]
        X --> Y["engine pass\npi, claude or opencode, headless"]
        Y --> Z["QA pre-shift\nSHIP / BLOCK / UNSURE"]
        Z --> AA["bookkeeping on factory main:\nreport + events archived, status → review"]
    end

    C --> S
    AA --> M
    RE -.->|"next 01:17"| S
```

## Sequence diagram — one full day/night cycle

```mermaid
sequenceDiagram
    actor H as Day shift (human)
    participant C as cron (01:17)
    participant R as run.py (runner)
    participant E as Engine (pi / claude / opencode)
    participant T as Target repo

    H->>H: write order · lint · approve · commit
    Note over H,T: evening — the handover

    C->>R: nightly fire
    R->>R: factory lock · clean-tree check
    R->>R: collect queue (approved, linted)
    loop each order (max N per night)
        R->>T: repo lock · base_ref (ff local main)
        R->>T: git worktree add wo/NNN
        R->>E: headless pass (manual + order embedded)
        E->>T: implement + commit on wo/NNN
        E-->>R: JSON event stream → report
        R->>E: QA pre-shift (run the criteria)
        E-->>R: verdict SHIP / BLOCK / UNSURE
        R->>T: sweep WIP · remove worktree
        R->>R: bookkeeping on factory main\nreport archived · status → review
    end
    Note over H,T: morning — decisions only

    H->>R: status.py (floor report)
    H->>H: read QA verdict + diff
    alt good
        H->>T: accept.py NNN (squash-merge, done)
        H->>T: push the target
    else not there yet
        H->>T: status: blocked + question
        H->>H: re-approve for tomorrow night
    end
```

## The invariants both diagrams rely on

- Only the **day shift** moves work into or out of `approved`, `blocked`,
  `done`, `rejected` — and only the day shift merges or pushes.
- The **night shift** never touches a working copy: every order runs in a
  throwaway worktree on its own branch.
- Blocked or ambiguous → the night **stops and asks**; it never guesses.
