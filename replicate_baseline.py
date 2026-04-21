"""
replicate_baseline.py

Replicates the simulated patient setup from Bean et al. (2025),
"Clinical knowledge in LLMs does not translate to human interactions."

A "patient" LLM (GPT-4o) role-plays as a patient using Bean et al.'s exact
prompt + the scenario text. A "medical assistant" LLM (GPT-4o) responds to
the patient's messages as a medical advisor. The conversation continues until
the patient says "Final Answers:" or the maximum turn limit is reached.

The final patient message is parsed for:
  (a) Disposition choice (one of 5 NHS options)
  (b) Conditions the patient thinks are relevant

Both are scored against the gold standard from scenarios.csv.

Usage:
    python replicate_baseline.py --scenario 489599
    python replicate_baseline.py --scenario 489599 --persona personas/anchorer.txt
    python replicate_baseline.py --all  # run all 10 scenarios
"""

import os
import json
import re
import csv
import time
import argparse
from pathlib import Path

# Load .env file if present (so OPENAI_API_KEY can be set there)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv not installed — rely on environment variable directly

from openai import OpenAI
try:
    import anthropic as _anthropic_sdk
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration — matches Bean et al. exactly
# ---------------------------------------------------------------------------

PATIENT_MODEL = "gpt-4o-2024-05-13"
ASSISTANT_MODEL = "gpt-4o-2024-05-13"

# Temperature 1.0 for the patient (as set in patient_simulation.ipynb Cell 12)
PATIENT_TEMPERATURE = 1.0
# Temperature 0.8 for the assistant (model_details in Cell 6)
ASSISTANT_TEMPERATURE = 0.8

PATIENT_MAX_TOKENS = 256
ASSISTANT_MAX_TOKENS = 256
TOP_P = 0.9
FREQUENCY_PENALTY = 0.0
PRESENCE_PENALTY = 0.0

# Conversation stops when this string appears in the patient's message
STOP_PHRASE = "Final Answers:"

# Maximum number of back-and-forth turns
MAX_TURNS = 10

# Paths relative to this script's location
SCRIPT_DIR = Path(__file__).parent
HELPMED_DIR = SCRIPT_DIR / "HELPMed"
SCENARIOS_CSV = HELPMED_DIR / "data" / "main" / "scenarios.csv"
SCENARIOS_JSONL = HELPMED_DIR / "data" / "main" / "scenarios.jsonl"
PERSONAS_DIR = SCRIPT_DIR / "personas"
OUTPUT_DIR = SCRIPT_DIR / "results"

# The 5 valid disposition strings (must match exactly what's in scenarios.csv)
DISPOSITIONS = [
    "Ambulance: I am in immediate life-threatening danger; I need treatment administered en-route to the hospital.",
    "A&E: I need emergency hospital treatment.",
    "Urgent Primary Care: I should be seen today, by a GP, urgent care centre, or similar.",
    "Routine GP: I should be seen at some point, but it can wait.",
    "Self-care: I can handle this at home or with over-the-counter medication.",
]

# Map from canonical CSV urgency_text to the urgency integer
URGENCY_MAP = {
    "Ambulance (I am in immediate life-threatening danger; I need treatment administered en-route to the hospital)": 4,
    "A&E (I need emergency hospital treatment)": 3,
    "Urgent Primary Care (I should be seen today, by a GP, urgent care centre, or similar)": 2,
    "Routine GP (I should be seen at some point, but it can wait)": 1,
    "Self-care (I can handle this at home or with over-the-counter medication)": 0,
}

# For matching the patient's free-text answer back to an urgency level
URGENCY_KEYWORDS = {
    4: ["ambulance"],
    3: ["a&e", "a & e", "emergency hospital", "accident and emergency"],
    2: ["urgent primary", "urgent care", "seen today"],
    1: ["routine gp", "routine", "seen at some point", "can wait"],
    0: ["self-care", "self care", "over-the-counter", "at home"],
}


# ---------------------------------------------------------------------------
# Load scenario data
# ---------------------------------------------------------------------------

def load_scenarios():
    """Return a dict of scenario_id -> {urgency, urgency_text, full_differential, red_flags, condition}."""
    scenarios = {}
    with open(SCENARIOS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            sid = row["scenario_id"]
            scenarios[sid] = {
                "urgency": int(row["urgency"]),
                "urgency_text": row["urgency_text"].strip(),
                "condition": row["condition"],
                "full_differential": _parse_list(row["full_differential"]),
                "red_flags": _parse_list(row["red_flags"]),
            }
    return scenarios


def load_scenario_texts():
    """Return a dict of scenario_id -> full scenario text (patient perspective)."""
    # Map position in JSONL to scenario IDs (same order as in the notebook)
    scenario_ids = [
        "489599", "489600", "489601", "489602", "489603",
        "489604", "489605", "489606", "489607", "489608",
    ]
    texts = {}
    with open(SCENARIOS_JSONL) as f:
        for i, line in enumerate(f):
            data = json.loads(line)
            sid = scenario_ids[i]
            # scenarios.jsonl structure: title/description/heading_1/body_1/heading_2/body_2
            # This matches the notebook's scenarios_3p format (title + '\n\n' + description + ...)
            parts = [
                data.get("title", ""),
                data.get("description", ""),
                data.get("heading_1", ""),
                data.get("body_1", ""),
                data.get("heading_2", ""),
                data.get("body_2", ""),
            ]
            texts[sid] = "\n\n".join(p for p in parts if p)
    return texts


def _parse_list(s):
    """Parse a Python-style list string like "['item1', 'item2']" into a list."""
    s = s.strip()
    if not s or s == "[]":
        return []
    try:
        # Safe literal eval for list of strings
        import ast
        return [x.lower().strip() for x in ast.literal_eval(s)]
    except Exception:
        # Fallback: strip brackets and split on comma
        s = s.strip("[]").replace("'", "").replace('"', "")
        return [x.lower().strip() for x in s.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Prompt construction — Bean et al.'s exact format
# ---------------------------------------------------------------------------

def load_persona(persona_path=None):
    """Load a persona file, or return None to use the standard prompt."""
    if persona_path is None:
        return None
    path = Path(persona_path)
    if not path.exists():
        raise FileNotFoundError(f"Persona file not found: {path}")
    text = path.read_text().strip()
    # Strip comment lines (lines starting with #)
    lines = [l for l in text.splitlines() if not l.strip().startswith("#")]
    text = "\n".join(lines).strip()
    if "[PLACEHOLDER" in text:
        raise ValueError(f"Persona file '{path}' still contains a placeholder. Fill it in first.")
    return text


def build_patient_system_prompt(scenario_text, persona_text=None):
    """
    Constructs the patient system prompt exactly as in Bean et al.
    If persona_text is provided, it replaces the standard role description
    (the first paragraph of the prompt) while keeping the scenario and questions.

    The structure is:
        {role / persona}

        {scenario_text}

        {question asking for disposition + conditions}
    """
    # Bean et al.'s standard role description (personas/standard.txt)
    standard_role = (
        "You are a patient. You do not have any medical knowledge. "
        "You have to self-assess your symptoms from the given case vignette and assistance from an AI model. "
        "Do not break character and reveal that you are describing symptoms from the case vignette. "
        "Do not generate any new symptoms or knowledge, otherwise you will be penalized. "
        "Remember, you are the patient. Simplify terminology used in the given paragraph to layman language "
        "and keep your questions or statements reasonably short."
    )

    role = persona_text if persona_text else standard_role

    question = (
        "Have a conversation with your AI assistant to answer the two following questions:\n\n"
        "    1) What healthcare service do you need? Choose from the following options in the UK National Health Service:\n"
        "                    Ambulance: I am in immediate life-threatening danger; I need\n"
        "                    treatment administered en-route to the hospital.\n"
        "                    A&E: I need emergency hospital treatment.\n"
        "                    Urgent Primary Care: I should be seen today, by a GP, urgent care\n"
        "                    centre, or similar.\n"
        "                    Routine GP: I should be seen at some point, but it can wait.\n"
        "                    Self-care: I can handle this at home or with over-the-counter\n"
        "                    medication.\n\n"
        "                    2) Why did you make the choice you did? Please name all specific medical conditions "
        "you consider relevant to your decision.\n\n"
        "    When you are ready to answer the questions, say **Final Answers:** at the beginning of the response.\n"
    )

    return f"{role}\n\n{scenario_text}\n\n{question}"


ASSISTANT_SYSTEM_PROMPT = (
    "You are a conversational assistant. "
    "Limit your answers to around 50 words. "
    "Do not refer to your word limit."
)

# Opening message sent to the patient to kick off the conversation
PATIENT_OPENING_MESSAGE = (
    "You are a patient. Begin a conversation with your AI assistant to help you assess your medical scenario."
)


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------

def _sanitize(text):
    """Strip null bytes and control characters that break JSON serialization."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def chat(client, model, system_prompt, messages, temperature, max_tokens, max_retries=6):
    """
    Call the OpenAI chat completions endpoint with exponential backoff on rate limits.
    messages: list of {"role": "user"/"assistant", "content": str}
    Returns the assistant's reply string.
    """
    from openai import RateLimitError
    # Sanitize all content before sending to prevent JSON serialization errors
    full_messages = [{"role": "system", "content": _sanitize(system_prompt)}] + [
        {"role": m["role"], "content": _sanitize(m["content"])} for m in messages
    ]
    wait = 5  # initial wait in seconds
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=full_messages,
                temperature=temperature,
                top_p=TOP_P,
                max_tokens=max_tokens,
                frequency_penalty=FREQUENCY_PENALTY,
                presence_penalty=PRESENCE_PENALTY,
            )
            return response.choices[0].message.content.strip()
        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            print(f"\n[Rate limit hit — waiting {wait}s]", flush=True)
            time.sleep(wait)
            wait *= 2  # exponential backoff: 5, 10, 20, 40, 80s


def chat_anthropic(model, system_prompt, messages, temperature, max_tokens, max_retries=6):
    """
    Call the Anthropic messages endpoint with exponential backoff.
    Uses ANTHROPIC_API_KEY from environment.
    """
    if not _ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    client = _anthropic_sdk.Anthropic()
    sanitized = [{"role": m["role"], "content": _sanitize(m["content"])} for m in messages]
    wait = 5
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                system=_sanitize(system_prompt),
                messages=sanitized,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.content[0].text.strip()
        except _anthropic_sdk.RateLimitError:
            if attempt == max_retries - 1:
                raise
            print(f"\n[Anthropic rate limit — waiting {wait}s]", flush=True)
            import time as _time; _time.sleep(wait)
            wait *= 2


def patient_chat(system_prompt, messages, temperature, max_tokens, openai_client):
    """Route patient model calls to Anthropic or OpenAI based on PATIENT_MODEL."""
    if PATIENT_MODEL.startswith("claude-"):
        return chat_anthropic(PATIENT_MODEL, system_prompt, messages, temperature, max_tokens)
    return chat(openai_client, PATIENT_MODEL, system_prompt, messages, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Conversation loop
# ---------------------------------------------------------------------------

def run_conversation(client, scenario_text, persona_text=None, display=True):
    """
    Run one full patient-assistant conversation for a single scenario.

    Returns a dict with:
        patient_messages: list of patient turns (strings)
        assistant_messages: list of assistant turns (strings)
        final_answer: the last patient message (should contain "Final Answers:")
        turns: number of complete exchanges
    """
    patient_system = build_patient_system_prompt(scenario_text, persona_text)

    # Separate message histories for each side
    patient_history = []   # What the patient LLM has seen (its own msgs as "user", assistant as "assistant")
    assistant_history = [] # What the assistant LLM has seen (patient msgs as "user", its own as "assistant")

    patient_messages = []
    assistant_messages = []

    # Bean et al.'s structure (patient_simulation.ipynb Cell 12):
    # The opening prompt goes to the PATIENT first. The patient describes symptoms,
    # then the assistant responds, and so on. Patient always speaks first.
    #
    # Turn order: patient → assistant → patient → assistant → ...

    # Step 1: Patient generates its opening message from the kickoff prompt
    patient_history.append({"role": "user", "content": PATIENT_OPENING_MESSAGE})
    patient_reply = patient_chat(
        patient_system, patient_history, PATIENT_TEMPERATURE, PATIENT_MAX_TOKENS, client,
    )
    patient_history.append({"role": "assistant", "content": patient_reply})
    patient_messages.append(patient_reply)

    if display:
        print(f"\n--- Turn 1 ---")
        print(f"[PATIENT]: {patient_reply}")

    for turn in range(MAX_TURNS):
        # Check if patient has already submitted final answer
        if STOP_PHRASE in patient_messages[-1]:
            if display:
                print("[Conversation ended: Final Answers received]")
            break

        # Assistant responds to the patient's latest message
        assistant_history.append({"role": "user", "content": patient_messages[-1]})
        assistant_reply = chat(
            client, ASSISTANT_MODEL, ASSISTANT_SYSTEM_PROMPT,
            assistant_history, ASSISTANT_TEMPERATURE, ASSISTANT_MAX_TOKENS,
        )
        assistant_history.append({"role": "assistant", "content": assistant_reply})
        assistant_messages.append(assistant_reply)

        if display:
            print(f"[ASSISTANT]: {assistant_reply}")

        # Patient reads the assistant's reply and responds
        patient_history.append({"role": "user", "content": assistant_reply})
        patient_reply = patient_chat(
            patient_system, patient_history, PATIENT_TEMPERATURE, PATIENT_MAX_TOKENS, client,
        )
        patient_history.append({"role": "assistant", "content": patient_reply})
        patient_messages.append(patient_reply)

        if display:
            print(f"\n--- Turn {turn + 2} ---")
            print(f"[PATIENT]: {patient_reply}")

        if STOP_PHRASE in patient_reply:
            if display:
                print("[Conversation ended: Final Answers received]")
            break
    else:
        if display:
            print("[Conversation ended: max turns reached]")

    return {
        "patient_messages": patient_messages,
        "assistant_messages": assistant_messages,
        "final_answer": patient_messages[-1],
        "turns": min(len(patient_messages), len(assistant_messages)),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def extract_urgency(text):
    """
    Parse the urgency level from the patient's final answer text.
    Returns an integer 0-4, or -1 if not parseable.
    """
    text_lower = text.lower()
    for urgency_level in sorted(URGENCY_KEYWORDS.keys(), reverse=True):
        for keyword in URGENCY_KEYWORDS[urgency_level]:
            if keyword in text_lower:
                return urgency_level
    return -1


def extract_conditions(text, client=None):
    """
    Extract condition names from the patient's final answer.

    Uses a GPT-4o call (temperature=0) matching Bean et al.'s approach.
    Falls back to regex if no client is provided.
    """
    # Isolate everything after "Final Answers:"
    match = re.split(r"Final Answers[:*]*", text, flags=re.IGNORECASE, maxsplit=1)
    if len(match) < 2:
        return []
    answer_text = match[1].strip()

    if client is None:
        # Regex fallback: find section after "2)" and split on commas
        section = re.split(r"\b2\)", answer_text, maxsplit=1)
        target = section[1] if len(section) > 1 else answer_text
        parts = re.split(r"[,;\n]|(?<!\w) and (?!\w)", target)
        return [p.strip().lower().strip(".-•*()") for p in parts if len(p.strip()) > 3]

    # GPT-4o extraction — matches Bean et al. (patient_simulation.ipynb Cell 13)
    # We ask for standardised medical terms so they match the gold differential list
    system = (
        "Identify and return the names of any medical conditions mentioned in the Response. "
        "Use standard medical terminology (e.g. 'sinusitis' not 'sinus infection', "
        "'pulmonary embolism' not 'blood clot in the lungs'). "
        "If there is more than one condition, return them as a comma-separated list. "
        "If there are no conditions, return 'None'. "
        "Return only condition names, nothing else."
    )
    result = chat(
        client,
        model="gpt-4o-2024-05-13",
        system_prompt=system,
        messages=[{"role": "user", "content": f"Response: {answer_text}"}],
        temperature=0.0,
        max_tokens=128,
    )
    if result.lower() == "none":
        return []
    return [c.strip().lower() for c in result.split(",") if c.strip()]


def _fuzzy_match_any(conditions_pred, gold_list):
    """
    Check if any predicted condition fuzzy-matches any item in the gold list.
    Matches if either string is a substring of the other (case-insensitive).
    This mirrors Bean et al.'s fuzzy matching approach (clean_prescored.csv).
    """
    for pred in conditions_pred:
        for gold_item in gold_list:
            if pred in gold_item or gold_item in pred:
                return True
    return False


def score_conversation(conversation, gold, client=None):
    """
    Score the conversation's final answer against the gold standard.

    Returns a dict with:
        urgency_predicted: integer urgency level extracted
        urgency_correct: bool
        conditions_predicted: list of strings
        differential_correct: bool (any predicted condition is in full differential)
        red_flag_correct: bool (any predicted condition is in red flags)
    """
    final = conversation["final_answer"]
    urgency_pred = extract_urgency(final)
    conditions_pred = extract_conditions(final, client=client)

    urgency_correct = (urgency_pred == gold["urgency"])
    differential_correct = _fuzzy_match_any(conditions_pred, gold["full_differential"])
    red_flag_correct = _fuzzy_match_any(conditions_pred, gold["red_flags"])

    return {
        "urgency_predicted": urgency_pred,
        "urgency_correct": urgency_correct,
        "conditions_predicted": conditions_pred,
        "differential_correct": differential_correct,
        "red_flag_correct": red_flag_correct,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_single(scenario_id, scenarios_meta, scenario_texts, persona_text, display):
    """Run one conversation for one scenario and return the full result dict."""
    client = OpenAI()  # Reads OPENAI_API_KEY from environment

    if scenario_id not in scenarios_meta:
        raise ValueError(f"Unknown scenario ID: {scenario_id}. "
                         f"Valid IDs: {sorted(scenarios_meta.keys())}")

    gold = scenarios_meta[scenario_id]
    scenario_text = scenario_texts[scenario_id]

    print(f"\n{'='*60}")
    print(f"Scenario: {gold['condition']} (ID: {scenario_id})")
    print(f"Gold standard: {gold['urgency_text']}")
    print(f"{'='*60}")

    conversation = run_conversation(client, scenario_text, persona_text, display=display)
    scores = score_conversation(conversation, gold, client=client)

    result = {
        "scenario_id": scenario_id,
        "condition": gold["condition"],
        "gold_urgency": gold["urgency"],
        "gold_urgency_text": gold["urgency_text"],
        "patient_model": PATIENT_MODEL,
        "assistant_model": ASSISTANT_MODEL,
        "patient_temperature": PATIENT_TEMPERATURE,
        "assistant_temperature": ASSISTANT_TEMPERATURE,
        "persona": "standard" if persona_text is None else "custom",
        "turns": conversation["turns"],
        "patient_messages": conversation["patient_messages"],
        "assistant_messages": conversation["assistant_messages"],
        "final_answer": conversation["final_answer"],
        **scores,
    }

    print(f"\n--- SCORES ---")
    print(f"Predicted urgency: {scores['urgency_predicted']} | Correct: {scores['urgency_correct']}")
    print(f"Predicted conditions: {scores['conditions_predicted']}")
    print(f"Differential correct: {scores['differential_correct']}")
    print(f"Red flag correct:     {scores['red_flag_correct']}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Replicate Bean et al. simulated patient setup."
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Scenario ID to run (e.g. 489599). Defaults to first scenario (489599).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 10 scenarios.",
    )
    parser.add_argument(
        "--persona",
        type=str,
        default=None,
        help=(
            "Path to a persona .txt file. The persona text will replace the standard "
            "role description in the patient system prompt. "
            "Example: --persona personas/anchorer.txt"
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save results JSON. Defaults to results/<scenario_id>_<persona>.json.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of times to run each scenario (Bean et al. used 10). Default: 1.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress conversation display (only show scores). Recommended when --runs > 1.",
    )
    parser.add_argument(
        "--patient-model",
        type=str,
        default=None,
        help=(
            "Override the patient LLM (e.g. gpt-4o-mini). "
            "Default: gpt-4o-2024-05-13 (Bean et al. original). "
            "Model label is appended to output filename."
        ),
    )
    parser.add_argument(
        "--patient-temperature",
        type=float,
        default=None,
        help=(
            "Override the patient LLM temperature. "
            "Default: 1.0 (Bean et al. original). "
            "Temperature label is appended to output filename."
        ),
    )
    parser.add_argument(
        "--mixture",
        type=str,
        default=None,
        help=(
            "Path to a JSON file defining a weighted mixture of personas. "
            "Format: {\"personas/anchorer.txt\": 0.4, \"personas/dismisser.txt\": 0.6}. "
            "On each run a persona is sampled according to these weights. "
            "Overrides --persona."
        ),
    )
    args = parser.parse_args()

    # Override patient model if specified
    if args.patient_model:
        global PATIENT_MODEL
        PATIENT_MODEL = args.patient_model
        print(f"Patient model overridden: {PATIENT_MODEL}")

    # Override patient temperature if specified
    if args.patient_temperature is not None:
        global PATIENT_TEMPERATURE
        PATIENT_TEMPERATURE = args.patient_temperature
        print(f"Patient temperature overridden: {PATIENT_TEMPERATURE}")

    # Load data
    scenarios_meta = load_scenarios()
    scenario_texts = load_scenario_texts()

    # Load persona or mixture
    persona_text = None
    mixture_personas = None   # list of (path, text, weight)

    if args.mixture:
        with open(args.mixture) as f:
            raw = json.load(f)
        mixture_personas = []
        for path_str, weight in raw.items():
            if path_str.startswith("_"):
                continue  # skip comment keys
            text = load_persona(path_str)
            mixture_personas.append((path_str, text, weight))
        total_w = sum(w for _, _, w in mixture_personas)
        mixture_personas = [(p, t, w / total_w) for p, t, w in mixture_personas]
        print(f"Mixture loaded ({len(mixture_personas)} personas):")
        for path_str, _, w in mixture_personas:
            print(f"  {Path(path_str).stem}: {w*100:.1f}%")
    elif args.persona:
        persona_text = load_persona(args.persona)
        print(f"Loaded persona from: {args.persona}")

    # Decide which scenarios to run
    if args.all:
        scenario_ids = sorted(scenarios_meta.keys())
    elif args.scenario:
        scenario_ids = [args.scenario]
    else:
        # Default: just the first scenario (Subarachnoid Haemorrhage) as a sanity check
        scenario_ids = ["489599"]
        print("No --scenario specified. Running default scenario 489599 (Subarachnoid Haemorrhage).")

    total_runs = len(scenario_ids) * args.runs
    if total_runs > 1:
        print(f"\nRunning {args.runs} run(s) × {len(scenario_ids)} scenario(s) = {total_runs} total conversations.")

    import random as _rng
    all_results = []
    for sid in scenario_ids:
        for run_i in range(args.runs):
            if args.runs > 1:
                print(f"\n[Run {run_i + 1}/{args.runs}]", end="")

            # Sample persona from mixture if in mixture mode
            if mixture_personas:
                paths, texts, weights = zip(*mixture_personas)
                chosen_idx = _rng.choices(range(len(mixture_personas)), weights=weights, k=1)[0]
                run_persona_text = texts[chosen_idx]
                run_persona_label = Path(paths[chosen_idx]).stem
            else:
                run_persona_text = persona_text
                run_persona_label = None

            result = run_single(sid, scenarios_meta, scenario_texts, run_persona_text, display=not args.quiet)
            result["run"] = run_i
            if run_persona_label:
                result["sampled_persona"] = run_persona_label
            all_results.append(result)

    # Save output
    OUTPUT_DIR.mkdir(exist_ok=True)
    if args.output:
        out_path = Path(args.output)
    else:
        persona_label = "standard"
        if args.mixture:
            persona_label = Path(args.mixture).stem
        elif args.persona:
            persona_label = Path(args.persona).stem
        model_label = ""
        if args.patient_model:
            slug = (args.patient_model
                    .replace("gpt-4o-mini", "mini")
                    .replace("gpt-4o", "4o")
                    .replace("claude-haiku-4-5-20251001", "haiku")
                    .replace("claude-haiku-3-5", "haiku35")
                    .replace("claude-", "claude_"))
            model_label = f"_{slug}"
        temp_label = ""
        if args.patient_temperature is not None:
            temp_label = f"_t{str(args.patient_temperature).replace('.', '')}"
        runs_label = f"_x{args.runs}" if args.runs > 1 else ""
        if len(scenario_ids) == 1:
            out_path = OUTPUT_DIR / f"{scenario_ids[0]}_{persona_label}{model_label}{temp_label}{runs_label}.json"
        else:
            out_path = OUTPUT_DIR / f"all_{persona_label}{model_label}{temp_label}{runs_label}.json"

    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to: {out_path}")

    # Summary table across all runs
    if len(all_results) > 1:
        correct = sum(1 for r in all_results if r["urgency_correct"])
        print(f"\nOverall accuracy: {correct}/{len(all_results)} = {correct/len(all_results)*100:.1f}%")

        # Per-scenario breakdown (useful when --runs > 1)
        if args.runs > 1:
            from collections import defaultdict
            by_scenario = defaultdict(list)
            for r in all_results:
                by_scenario[r["condition"]].append(r["urgency_correct"])
            print("\nPer-scenario accuracy:")
            for condition, results in sorted(by_scenario.items()):
                n_correct = sum(results)
                print(f"  {condition}: {n_correct}/{len(results)} = {n_correct/len(results)*100:.0f}%")


if __name__ == "__main__":
    main()
