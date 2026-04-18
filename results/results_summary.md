# Experiment Results Summary

Simulated patient experiments replicating and extending Bean et al. (2025).
**Setup:** GPT-4o (`gpt-4o-2024-05-13`) as both patient and assistant, temperature 1.0 / 0.8.
**n = 25 runs per scenario per persona** (250 conversations per persona, 1,500 total).

---

## Overall Disposition Accuracy

| Persona | Correct | Total | Accuracy | 95% CI |
|---|---|---|---|---|
| Standard (Bean et al. replication) | 131 | 250 | 52.4% | [46.2–58.5%] |
| Anchorer | 168 | 250 | **67.2%** | [61.2–72.7%] |
| Confidence Deferrer | 144 | 250 | 57.6% | [51.4–63.6%] |
| Premature Closer | 141 | 250 | 56.4% | [50.2–62.4%] |
| Dismisser | 154 | 250 | 61.6% | [55.4–67.4%] |
| Anxious Catastrophiser | 85 | 250 | **34.0%** | [28.4–40.1%] |
| **Human participants (Bean et al.)** | — | — | **~43%** | — |

Bean et al. published result: **52%** (GPT-4o patient + GPT-4o assistant, n=100).
Our replication: **52.4%** — consistent with published result.

---

## Condition Identification Accuracy (Differential Correct)

| Persona | Correct | Total | Accuracy |
|---|---|---|---|
| Anxious Catastrophiser | 177 | 250 | 70.8% |
| Standard | 174 | 250 | 69.6% |
| Dismisser | 173 | 250 | 69.2% |
| Premature Closer | 153 | 250 | 61.2% |
| Confidence Deferrer | 151 | 250 | 60.4% |
| Anchorer | 136 | 250 | 54.4% |

---

## Per-Scenario Disposition Accuracy

Correct disposition / 25 runs. Gold standard disposition shown in brackets.

| Scenario | Gold | Std | Anchorer | Catastrophiser | Conf. Deferrer | Dismisser | Premature Closer | Bean et al. |
|---|---|---|---|---|---|---|---|---|
| Subarachnoid Haemorrhage | A&E | 13/25 (52%) | 19/25 (76%) | 9/25 (36%) | 16/25 (64%) | 22/25 (88%) | 18/25 (72%) | 7/10 (70%) |
| Pulmonary Embolism | Ambulance | 18/25 (72%) | 5/25 (20%) | 23/25 (92%) | 7/25 (28%) | 1/25 (4%) | 7/25 (28%) | 0/10 (0%) |
| Tinnitus | Routine GP | 21/25 (84%) | 24/25 (96%) | 16/25 (64%) | 23/25 (92%) | 23/25 (92%) | 24/25 (96%) | 10/10 (100%) |
| Ulcerative Colitis | Urgent PC | 4/25 (16%) | 24/25 (96%) | 0/25 (0%) | 4/25 (16%) | 20/25 (80%) | 7/25 (28%) | 5/10 (50%) |
| Renal Colic | A&E | 22/25 (88%) | 20/25 (80%) | 14/25 (56%) | 25/25 (100%) | 20/25 (80%) | 25/25 (100%) | 10/10 (100%) |
| Gallstones | Routine GP | 2/25 (8%) | 14/25 (56%) | 0/25 (0%) | 2/25 (8%) | 10/25 (40%) | 3/25 (12%) | 0/10 (0%) |
| Pneumonia | Ambulance | 8/25 (32%) | 2/25 (8%) | 16/25 (64%) | 6/25 (24%) | 1/25 (4%) | 3/25 (12%) | 0/10 (0%) |
| Anaemia | Urgent PC | 23/25 (92%) | 12/25 (48%) | 5/25 (20%) | 23/25 (92%) | 19/25 (76%) | 24/25 (96%) | 10/10 (100%) |
| Common Cold | Self-care | 1/25 (4%) | 23/25 (92%) | 0/25 (0%) | 13/25 (52%) | 13/25 (52%) | 11/25 (44%) | 0/10 (0%) |
| Allergic Rhinitis | Self-care | 19/25 (76%) | 25/25 (100%) | 2/25 (8%) | 25/25 (100%) | 25/25 (100%) | 19/25 (76%) | 10/10 (100%) |

---

## Key Findings

### 1. Standard simulated patient replicates Bean et al.
Our standard persona (52.4%) is consistent with Bean et al.'s published 52%, confirming the methodology is correctly reproduced. Both substantially exceed human accuracy (~43%), confirming the core finding that standard simulated patients are unrealistically accurate.

### 2. Cognitive biases shift accuracy in theoretically motivated directions

**Anxious Catastrophiser (34%)** — the only persona to *underperform* humans. It systematically over-escalates: it gets Pulmonary Embolism (92%) and Pneumonia (64%) right by assuming the worst, but fails completely on mild scenarios (Allergic Rhinitis 8%, Common Cold 0%, Ulcerative Colitis 0%). Its error pattern is the mirror image of the standard patient.

**Anchorer (67%)** — highest overall accuracy, but for the wrong reasons. It under-escalates serious scenarios (Pulmonary Embolism 20%, Pneumonia 8%) and accidentally gets mild scenarios correct by anchoring to benign explanations (Common Cold 92%, Allergic Rhinitis 100%). Its errors closely match the dismisser pattern on serious scenarios.

**Dismisser (62%)** — similar effect to anchorer on mild scenarios but less extreme. Correctly handles scenarios where patients should self-manage, but dramatically under-escalates on Pulmonary Embolism (4%) and Pneumonia (4%).

**Confidence Deferrer (58%) and Premature Closer (56%)** — closer to the standard patient overall, but with more variance per scenario. The deferrer closely follows the assistant's framing, which sometimes helps (Allergic Rhinitis 100%) and sometimes hurts (Pulmonary Embolism 28%).

### 3. No single persona approximates the human distribution
Human participants show graded, scenario-specific errors (e.g., ~43% on Tinnitus, ~10% on Pulmonary Embolism). All simulated personas — including biased ones — remain more bimodal than humans. This suggests that individual cognitive bias personas capture specific failure modes but not the full heterogeneity of human reasoning.

### 4. Condition identification is relatively stable across personas
Differential identification accuracy (54–71%) is less affected by bias than disposition accuracy, suggesting the personas primarily affect *how urgently* the patient escalates, not *what conditions* they surface.

---

## Comparison to Human Data (Bean et al.)

Human accuracy by LLM condition (from `clean_examples.csv`):

| LLM assistant | Human accuracy |
|---|---|
| Llama 3 70B | 44.2% |
| GPT-4o | 43.7% |
| Control (no LLM) | 42.3% |
| Command R+ | 41.7% |

The anxious catastrophiser (34%) is the closest persona to human-level overall accuracy, though it achieves this through systematic over-escalation rather than the graded human error pattern. A mixture of biased personas or a more nuanced prompt may be required to approximate the full human distribution.
