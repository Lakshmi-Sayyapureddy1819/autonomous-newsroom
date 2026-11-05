# Interview cheat sheet (one page)

Sources: `DELIVERY.md`, `docs/token-report.md`, `agents/demo/DEMO_GUIDE.md`, `agents/PROTOCOL.md`.
Token numbers are runtime-reported, not provider billing; no dollar cost is claimed.

## 1. Live change test

**Before the call (do a rehearsal the day before; a clean run took about 15 minutes)**
- Clean checkout of `main`: `git fetch && git switch main && git pull`.
- `bash agents/demo/run_local_demo.sh --preflight-only` (changes nothing on GitHub).
- Quota check. If OpenRouter's free quota is exhausted, set the per-run overrides first:
  ```
  export NEWSROOM_EXTRA_ARGS_EDITOR="-m gemini-2.5-flash --provider gemini"
  export NEWSROOM_EXTRA_ARGS_COPYDESK="-m gemini-2.5-flash --provider gemini"
  export NEWSROOM_EXTRA_ARGS_FACTCHECK="--model google/gemini-2.5-flash"
  ```
- Laptop awake, Hermes gateway running, no other open PRs or active tickets.

**On the call**
```
bash agents/demo/run_local_demo.sh --yes --task "<their small change>"
```
Hermes Editor writes the Issue -> dispatcher wakes OpenClaw Reporter (PR) -> Hermes Copydesk
(review) -> OpenClaw Factcheck (tests the exact head) -> script stops at READY FOR HUMAN MERGE.
You merge in the browser. Narrate the labels moving. Tell them up front: 10 to 20 minutes.
Proof of past clean runs if a provider flakes: PR #36 and PR #38.

## 2. Architecture walkthrough

| Role | Runtime | Job | Model (DELIVERY.md) |
|---|---|---|---|
| editor | Hermes | task or brief -> Issues | nvidia/nemotron-3-ultra-550b-a55b:free |
| reporter | OpenClaw | builds, opens the PR | google/gemini-2.5-flash |
| copydesk | Hermes | reviews against the criteria | google/gemma-4-31b-it:free; in practice gemini-2.5-flash after 429s |
| factcheck | OpenClaw | tests the exact PR head | nvidia/nemotron-3.5-lightning:free |
| human | you | only merger; secrets and infra | none |

- Why these models: free tiers, and a different family for builder and reviewer. Say the setup
  diverged from the plan (Copydesk fell back to Gemini because the free model returned 429).
- Dispatcher: plain code, no LLM; wakes only the agent named by `agent:*`; GitHub is the only channel.
- Gates that blocked bad work: T2 rejected (missing malformed-feed and timestamp handling, fixed on
  attempt 2); T3 rejected (unsafe empty-summary handling, passed with 40 tests on attempt 2);
  PR #13 test change rejected and reverted. The gate needs `ci` + `review:approved` + `test:passed`.

## 3. Token and error post-mortem

- Ticket-linked roster runs: 1.55M input, 84k output. All included usage: 26.1M input, 1.07M
  output, mostly interactive sessions. Cache-read (519M) is re-read context; keep it separate.
- Honest point: the agents' own handoff token estimates were far too low; real counts were
  recovered afterwards from the Hermes and OpenClaw stores.
- 429/402: product summarizer = OpenRouter primary, Gemini fallback, both fail -> summary left
  empty and run marked partial (tested with a mocked 429). Agents: stop on 402/429, dispatcher
  backs off 30x longer, escalates to the human after 3 failures. Today's fix: per-run model override.
- One thing that broke: a Reporter left conflicting labels, the dispatcher counted it as progress
  and then skipped the ticket forever, so Copydesk and Factcheck never ran (#29, #31, #33). Fix:
  validate every handoff against GitHub. Proof: mutation test plus two clean live runs (#35, #37).
  Second story: a lost Hermes gateway caused a duplicate Copydesk run; now an uncertain outcome
  waits for GitHub instead of re-running.

## Say these limits yourself
- Everything ran on the laptop; the Oracle VM was never deployed.
- Copydesk and Factcheck are LLMs; the dispatcher validates the shape of a handoff, not review quality.
- Free-tier quotas are fragile; keep a Gemini override ready.
