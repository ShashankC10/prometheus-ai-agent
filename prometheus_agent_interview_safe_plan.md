# Prometheus AI Agent — Interview-Safe Improvement Plan

## Goal

Make the project significantly stronger for interviews by improving:
- reliability
- technical depth
- evaluation rigor
- production realism
- how defensible the claims are

This plan focuses only on the highest-impact changes.

---

## Top priorities

### 1. Add schema-grounded PromQL generation
**Why this matters**
Right now the biggest interview risk is: “How do you stop the model from hallucinating metrics or labels?”

**What to build**
- fetch available metric names from Prometheus
- fetch label keys / example label values for shortlisted metrics
- create a metric catalog the agent can consult before generating PromQL
- force query generation to use only discovered metrics when possible

**Deliverables**
- `metric_catalog` module
- tool that returns candidate metrics for a user question
- prompt update that grounds query generation in discovered metrics

**Interview-safe claim after this**
> Built a schema-grounded observability agent that reduced hallucinated PromQL by grounding query generation in live Prometheus metadata.

---

### 2. Add PromQL validation and retry
**Why this matters**
A strong interviewer will ask what happens when the generated query is invalid.

**What to build**
- syntax / execution pre-check before full query execution
- classify query failures:
  - invalid metric
  - invalid label
  - empty result
  - timeout / expensive query
- retry loop:
  1. inspect failure
  2. revise query
  3. retry once or twice
- enforce safety limits:
  - max range
  - max step size
  - timeout cap

**Deliverables**
- query validator
- retry controller
- structured error handling
- safe query policy

**Interview-safe claim after this**
> Added validation and retry logic for LLM-generated PromQL, improving execution reliability and making the agent safer for observability workflows.

---

### 3. Add an evaluation suite
**Why this matters**
This is the single biggest missing piece. Without evals, the project is interesting but hard to defend rigorously.

**What to build**
Create a benchmark dataset with:
- natural-language monitoring questions
- expected metric families
- acceptable PromQL queries
- expected issue categories / summaries

**Measure**
- PromQL execution success rate
- hallucinated metric rate
- query semantic correctness
- summary usefulness / issue classification accuracy

**Deliverables**
- `evals/` folder
- 30–50 benchmark prompts
- evaluation script
- results table in README

**Interview-safe claim after this**
> Built a benchmark suite for NL-to-PromQL generation and incident summarization, measuring execution success, hallucination rate, and summary quality.

---

### 4. Make the agent truly multi-step
**Why this matters**
Right now a skeptical interviewer can still say this is “prompt + tools.”
This change makes the “agent” label much stronger.

**What to build**
Explicit workflow:
1. classify user question
2. decide whether metric discovery is needed
3. generate or refine PromQL
4. run one or more queries
5. optionally run anomaly detection
6. synthesize evidence-backed answer

**Add question-type routing**
- metric lookup
- anomaly investigation
- alert explanation
- latency / error triage
- resource saturation analysis

**Deliverables**
- planner / router
- multi-step investigation state
- visible tool trace in output

**Interview-safe claim after this**
> Built a multi-step observability agent that planned investigations, selected tools, refined failed queries, and synthesized evidence-backed operational summaries.

---

### 5. Upgrade anomaly detection beyond global z-score
**Why this matters**
Global z-score is a fine baseline, but it is also the easiest thing for an interviewer to dismiss.

**What to build**
- rolling-window baseline
- median / MAD based anomaly detection
- sustained degradation detection
- change-point or step-change detection
- classify anomaly types:
  - spike
  - dip
  - sustained regression
  - step change

**Deliverables**
- anomaly detector v2
- comparison against current z-score baseline
- benchmark or case-study examples

**Interview-safe claim after this**
> Improved anomaly detection from a simple z-score baseline to rolling and robust baselines that better separated transient spikes from sustained regressions.

---

## Strong second-wave improvements

### 6. Add incident investigation packs
Predefined workflows for:
- high latency
- high error rate
- pod instability
- database bottleneck
- resource saturation

Each pack should gather multiple signals before summarizing.

**Why this matters**
This makes the project feel like an observability system instead of a query toy.

---

### 7. Add structured outputs
Return:
- issue category
- suspected service
- evidence metrics
- confidence
- anomalies found
- recommended next actions

**Why this matters**
Structured outputs are easier to test, easier to demo, and more realistic for engineering tools.

---

### 8. Add runbook / alert-rule grounding
Let the agent use:
- alert rules
- runbooks
- common metric mappings
- service-specific context

**Why this matters**
This helps the system give operationally useful answers instead of generic summaries.

---

## Suggested implementation order

### Phase 1 — highest ROI
1. schema-grounded metric discovery
2. PromQL validation + retry
3. evaluation suite

### Phase 2 — strengthen “agent” claim
4. multi-step planner / router
5. visible tool trace
6. structured outputs

### Phase 3 — improve technical depth
7. anomaly detection v2
8. incident investigation packs

### Phase 4 — production realism
9. runbook / alert-rule grounding
10. topology / dependency awareness

---

## What to change on the resume only after these improvements

After Phase 1 and Phase 2, the project can more safely support claims like:
- schema-grounded observability agent
- validated NL-to-PromQL generation
- multi-step incident investigation
- evidence-backed operational summaries

After Phase 3, you can more safely claim:
- robust anomaly detection
- incident triage workflows
- reduced invalid-query and false-summary behavior

Do **not** strengthen claims like “root-cause analysis” unless you add stronger causal reasoning or very careful evidence-based phrasing.

---

## Recommended final project positioning

Once the top improvements are complete, the best way to describe the project is:

> Built a schema-grounded observability agent that converts natural-language monitoring questions into validated PromQL, performs multi-step incident investigations using Prometheus tools, detects anomalies with robust time-series methods, and returns evidence-backed operational summaries.

---

## Minimum version that becomes interview-safe fast

If time is limited, do these 4 only:
1. metric grounding
2. query validation + retry
3. evaluation suite
4. multi-step routing / tool selection

These four changes will give the biggest improvement in both technical credibility and interview defensibility.
