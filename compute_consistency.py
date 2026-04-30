"""
Persona consistency scoring (Abdulhai et al. 2025 framework).

For each persona condition, samples conversations stratified by scenario and
scores them with GPT-4o-as-judge (temperature=0) on three dimensions:

  1. Prompt-to-line: does each patient turn align with the persona description?
  2. Line-to-line:   does the patient contradict themselves across turns?
  3. Q&A:            do answers about own history stay factually consistent?

Outputs results/consistency_scores.json.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
PERSONA_DIR = ROOT / "personas"
RESULTS_DIR = ROOT / "results"
OUT_PATH = RESULTS_DIR / "consistency_scores.json"

PERSONA_FILES = {
    "Standard":               ("standard.txt",               "all_standard_x25.json"),
    "Anchorer":               ("anchorer.txt",               "all_anchorer_x25.json"),
    "Anxious Catastrophiser": ("anxious_catastrophiser.txt", "all_anxious_catastrophiser_x25.json"),
    "Dismisser":              ("dismisser.txt",              "all_dismisser_x25.json"),
    "Premature Closer":       ("premature_closer.txt",       "all_premature_closer_x25.json"),
    "Confidence Deferrer":    ("confidence_deferrer.txt",    "all_confidence_deferrer_x25.json"),
}

N_PER_PERSONA = 25  # 25 conversations / persona, stratified by scenario where possible
JUDGE_MODEL = "gpt-4o-2024-11-20"
SEED = 42


# ---------- judge prompts ----------

PROMPT_TO_LINE_SYSTEM = (
    "You are evaluating whether a single patient turn aligns with a persona "
    "description. Respond with ONLY an integer 1-5. "
    "5 = clearly enacts the persona's distinctive behaviour. "
    "3 = neutral / generic patient turn. "
    "1 = directly contradicts the persona."
)

LINE_TO_LINE_SYSTEM = (
    "You are evaluating internal consistency across a patient's turns in one "
    "conversation. Respond with ONLY an integer 1-5. "
    "5 = no contradictions, stable tone and stance. "
    "3 = minor drift. "
    "1 = clear self-contradictions about symptoms, history, or stance."
)

QA_SYSTEM = (
    "You are evaluating whether a patient gives factually consistent answers "
    "about their OWN history (symptoms, timing, prior conditions, medications) "
    "when the AI asks similar questions. Respond with ONLY an integer 1-5. "
    "5 = always consistent. 3 = one minor slip. 1 = repeatedly contradicts own facts."
)


def parse_score(text: str) -> int | None:
    m = re.search(r"[1-5]", text or "")
    return int(m.group(0)) if m else None


def call_judge(client: OpenAI, system: str, user: str, retries: int = 3) -> int | None:
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                temperature=0,
                max_tokens=4,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return parse_score(resp.choices[0].message.content)
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"  judge error after {retries} tries: {exc}")
                return None
            time.sleep(2 ** attempt)
    return None


# ---------- sampling ----------

def stratified_sample(runs: list[dict], n: int, rng: random.Random) -> list[dict]:
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        if r.get("patient_messages"):
            by_scenario[r["condition"]].append(r)
    scenarios = sorted(by_scenario)
    if not scenarios:
        return []
    per = max(1, n // len(scenarios))
    sampled: list[dict] = []
    for s in scenarios:
        pool = by_scenario[s]
        rng.shuffle(pool)
        sampled.extend(pool[:per])
    rng.shuffle(sampled)
    return sampled[:n]


# ---------- scoring loop ----------

def score_persona(client: OpenAI, name: str, persona_text: str, runs: list[dict]) -> dict:
    rng = random.Random(SEED)
    sample = stratified_sample(runs, N_PER_PERSONA, rng)
    print(f"\n[{name}] sampled {len(sample)} conversations")

    p2l_scores: list[int] = []
    l2l_scores: list[int] = []
    qa_scores: list[int] = []
    n_turns = 0

    for i, run in enumerate(sample, 1):
        patient_turns = run["patient_messages"]
        assistant_turns = run.get("assistant_messages", [])
        if not patient_turns:
            continue

        # Prompt-to-line: score every patient turn against persona description.
        for t_idx, turn in enumerate(patient_turns):
            user = (
                f"PERSONA DESCRIPTION:\n{persona_text}\n\n"
                f"PATIENT TURN (turn {t_idx + 1} of {len(patient_turns)}):\n{turn}\n\n"
                "Rate alignment 1-5:"
            )
            s = call_judge(client, PROMPT_TO_LINE_SYSTEM, user)
            if s is not None:
                p2l_scores.append(s)
            n_turns += 1

        # Build a transcript view for whole-conversation judgements.
        transcript_lines = []
        for j in range(max(len(patient_turns), len(assistant_turns))):
            if j < len(patient_turns):
                transcript_lines.append(f"PATIENT: {patient_turns[j]}")
            if j < len(assistant_turns):
                transcript_lines.append(f"AI: {assistant_turns[j]}")
        transcript = "\n".join(transcript_lines)

        l2l_user = (
            f"CONVERSATION TRANSCRIPT:\n{transcript}\n\n"
            "Rate the patient's internal consistency across their turns 1-5:"
        )
        s_l2l = call_judge(client, LINE_TO_LINE_SYSTEM, l2l_user)
        if s_l2l is not None:
            l2l_scores.append(s_l2l)

        qa_user = (
            f"CONVERSATION TRANSCRIPT:\n{transcript}\n\n"
            "Rate factual consistency of the patient's answers about their own "
            "history (symptoms, timing, medications) 1-5:"
        )
        s_qa = call_judge(client, QA_SYSTEM, qa_user)
        if s_qa is not None:
            qa_scores.append(s_qa)

        if i % 5 == 0:
            print(f"  {i}/{len(sample)} done")

    def mean(xs: list[int]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "n_conversations": len(sample),
        "n_patient_turns": n_turns,
        "prompt_to_line_mean": mean(p2l_scores),
        "prompt_to_line_n": len(p2l_scores),
        "line_to_line_mean": mean(l2l_scores),
        "line_to_line_n": len(l2l_scores),
        "qa_mean": mean(qa_scores),
        "qa_n": len(qa_scores),
        "raw": {
            "prompt_to_line": p2l_scores,
            "line_to_line": l2l_scores,
            "qa": qa_scores,
        },
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing from .env")
    client = OpenAI(api_key=api_key)

    results: dict[str, dict] = {}
    for persona_name, (persona_file, runs_file) in PERSONA_FILES.items():
        persona_text = (PERSONA_DIR / persona_file).read_text().strip()
        runs_path = RESULTS_DIR / runs_file
        if not runs_path.exists():
            print(f"[skip] {persona_name}: missing {runs_file}")
            continue
        with open(runs_path) as f:
            runs = json.load(f)
        results[persona_name] = score_persona(client, persona_name, persona_text, runs)

        # Persist incrementally so a crash doesn't lose work.
        with open(OUT_PATH, "w") as f:
            json.dump({"judge_model": JUDGE_MODEL, "n_per_persona": N_PER_PERSONA,
                       "seed": SEED, "personas": results}, f, indent=2)

    print("\n=== Persona consistency (Abdulhai 2025 metrics) ===")
    print(f"{'Persona':<24} {'P→L':>6} {'L→L':>6} {'Q&A':>6} {'n_conv':>7}")
    for name, r in results.items():
        print(f"{name:<24} "
              f"{(r['prompt_to_line_mean'] or 0):>6.2f} "
              f"{(r['line_to_line_mean'] or 0):>6.2f} "
              f"{(r['qa_mean'] or 0):>6.2f} "
              f"{r['n_conversations']:>7}")
    print(f"\nSaved to {OUT_PATH}")


if __name__ == "__main__":
    main()
