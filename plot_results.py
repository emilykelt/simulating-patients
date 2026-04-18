"""
plot_results.py

Generates figures for the poster from the persona experiment results.
Outputs PNGs to results/figures/.
"""

import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).parent / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
FIGURES_DIR.mkdir(exist_ok=True)

PERSONAS = [
    ("Standard",               "all_standard_x25.json",               "#4878CF"),
    ("Anchorer",               "all_anchorer_x25.json",               "#6ACC65"),
    ("Dismisser",              "all_dismisser_x25.json",              "#D65F5F"),
    ("Premature Closer",       "all_premature_closer_x25.json",       "#B47CC7"),
    ("Confidence Deferrer",    "all_confidence_deferrer_x25.json",    "#C4AD66"),
    ("Anxious Catastrophiser", "all_anxious_catastrophiser_x25.json", "#77BEDB"),
]

# V2 personas (graded-uncertainty redesign). Catastrophiser v2 uses n=25;
# others use n=3 preliminary runs.
PERSONAS_V2 = [
    ("Anchorer v2",            "all_anchorer_v2_x3.json",                  "#6ACC65"),
    ("Dismisser v2",           "all_dismisser_v2_x3.json",                 "#D65F5F"),
    ("Premature Closer v2",    "all_premature_closer_v2_x3.json",          "#B47CC7"),
    ("Confidence Deferrer v2", "all_confidence_deferrer_v2_x3.json",       "#C4AD66"),
    ("Catastrophiser v2",      "all_anxious_catastrophiser_v2_x25.json",   "#77BEDB"),
]

# Paired for v1 vs v2 comparison (Standard excluded — no v2)
PERSONA_PAIRS = [
    ("Anchorer",               "Anchorer v2"),
    ("Dismisser",              "Dismisser v2"),
    ("Premature Closer",       "Premature Closer v2"),
    ("Confidence Deferrer",    "Confidence Deferrer v2"),
    ("Anxious Catastrophiser", "Catastrophiser v2"),
]

GOLD_URGENCY = {
    "Subarachnoid Haemorrhage": 3,
    "Pulmonary Embolism":       4,
    "Tinnitus":                 1,
    "Ulcerative Colitis":       2,
    "Renal Colic":              3,
    "Gallstones":               1,
    "Pneumonia":                4,
    "Anaemia":                  2,
    "Common Cold":              0,
    "Allergic Rhinitis":        0,
}

SCENARIO_ORDER = [
    "Allergic Rhinitis", "Common Cold", "Tinnitus", "Gallstones",
    "Anaemia", "Ulcerative Colitis", "Renal Colic", "Subarachnoid Haemorrhage",
    "Pneumonia", "Pulmonary Embolism",
]

SCENARIO_SHORT = {
    "Allergic Rhinitis":        "Allergic\nRhinitis",
    "Common Cold":              "Common\nCold",
    "Tinnitus":                 "Tinnitus",
    "Gallstones":               "Gallstones",
    "Anaemia":                  "Anaemia",
    "Ulcerative Colitis":       "Ulcerative\nColitis",
    "Renal Colic":              "Renal\nColic",
    "Subarachnoid Haemorrhage": "Subarachnoid\nHaem.",
    "Pneumonia":                "Pneumonia",
    "Pulmonary Embolism":       "Pulmonary\nEmbolism",
}

HUMAN_ACCURACY = 43.0  # average across Bean et al. treatment conditions
BEAN_STANDARD  = 52.0  # Bean et al. published simulated patient result

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def load_all():
    data = {}
    for label, fname, color in PERSONAS:
        path = RESULTS_DIR / fname
        with open(path) as f:
            data[label] = json.load(f)
    for label, fname, color in PERSONAS_V2:
        path = RESULTS_DIR / fname
        if path.exists():
            with open(path) as f:
                data[label] = json.load(f)
    return data

def accuracy(runs):
    return sum(1 for r in runs if r["urgency_correct"]) / len(runs) * 100

def per_scenario_accuracy(runs):
    by_scenario = defaultdict(list)
    for r in runs:
        by_scenario[r["condition"]].append(r["urgency_correct"])
    return {c: sum(v) / len(v) * 100 for c, v in by_scenario.items()}

def wilson_ci(correct, total, z=1.96):
    p = correct / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    margin = z * ((p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5) / denom
    return centre - margin, centre + margin

# ---------------------------------------------------------------------------
# Figure 1: Overall accuracy bar chart
# ---------------------------------------------------------------------------

def fig_overall_accuracy(data):
    fig, ax = plt.subplots(figsize=(9, 5))

    labels = [p[0] for p in PERSONAS]
    colors = [p[2] for p in PERSONAS]
    accs, lo_errs, hi_errs = [], [], []

    for label, fname, color in PERSONAS:
        runs = data[label]
        correct = sum(1 for r in runs if r["urgency_correct"])
        total = len(runs)
        acc = correct / total * 100
        lo, hi = wilson_ci(correct, total)
        accs.append(acc)
        lo_errs.append(acc - lo * 100)
        hi_errs.append(hi * 100 - acc)

    x = np.arange(len(labels))
    bars = ax.bar(x, accs, color=colors, width=0.55, zorder=3,
                  yerr=[lo_errs, hi_errs], capsize=4,
                  error_kw={"elinewidth": 1.2, "ecolor": "#333333"})

    # Human baseline band
    ax.axhspan(41.7, 44.2, alpha=0.15, color="grey", zorder=0)
    ax.axhline(HUMAN_ACCURACY, color="grey", linewidth=1.5, linestyle="--", zorder=2,
               label=f"Human baseline ~{HUMAN_ACCURACY:.0f}%")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Disposition accuracy (%)", fontsize=11)
    ax.set_title("Overall disposition accuracy by patient persona\n(n = 25 runs per scenario, 250 total)",
                 fontsize=12, pad=12)
    ax.set_ylim(0, 85)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)

    # Annotate bars
    for bar, acc in zip(bars, accs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{acc:.0f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.legend(fontsize=9)
    plt.tight_layout()
    out = FIGURES_DIR / "fig1_overall_accuracy.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")

# ---------------------------------------------------------------------------
# Figure 2: Per-scenario heatmap
# ---------------------------------------------------------------------------

def fig_heatmap(data):
    # Human per-scenario accuracy averaged across all 4 treatment conditions
    # Source: HELPMed/data/main/clean_examples.csv
    human_per_scenario = {
        "Subarachnoid Haemorrhage": (18+32+20+13) / (49+66+60+61) * 100,
        "Pulmonary Embolism":       (4+9+14+10)   / (43+63+75+59) * 100,
        "Tinnitus":                 (47+68+54+59)  / (54+78+61+69) * 100,
        "Ulcerative Colitis":       (47+30+33+39)  / (71+56+57+63) * 100,
        "Renal Colic":              (23+26+13+19)  / (62+56+52+58) * 100,
        "Gallstones":               (33+23+35+33)  / (64+61+59+63) * 100,
        "Pneumonia":                (5+9+4+3)      / (57+76+63+60) * 100,
        "Anaemia":                  (37+30+17+17)  / (85+66+58+66) * 100,
        "Common Cold":              (23+17+26+26)  / (66+46+60+58) * 100,
        "Allergic Rhinitis":        (28+18+38+31)  / (49+32+55+43) * 100,
    }

    # Equal mixture: pool all persona runs
    all_runs = []
    for label, fname, color in PERSONAS:
        all_runs.extend(data[label])
    mixture_psa = per_scenario_accuracy(all_runs)

    row_labels = ["Human (Bean et al.)"] + [p[0] for p in PERSONAS] + ["Equal Mixture"]
    n_rows = len(row_labels)
    matrix = np.zeros((n_rows, len(SCENARIO_ORDER)))

    # First row: human data
    for j, scenario in enumerate(SCENARIO_ORDER):
        matrix[0, j] = human_per_scenario[scenario]

    # Persona rows
    for i, (label, fname, color) in enumerate(PERSONAS):
        psa = per_scenario_accuracy(data[label])
        for j, scenario in enumerate(SCENARIO_ORDER):
            matrix[i + 1, j] = psa.get(scenario, 0)

    # Last row: equal mixture
    for j, scenario in enumerate(SCENARIO_ORDER):
        matrix[-1, j] = mixture_psa.get(scenario, 0)

    fig, ax = plt.subplots(figsize=(13, 7.0))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")

    ax.set_xticks(np.arange(len(SCENARIO_ORDER)))
    ax.set_xticklabels([SCENARIO_SHORT[s] for s in SCENARIO_ORDER], fontsize=8.5)
    ax.set_yticks(np.arange(n_rows))
    ax.set_yticklabels(row_labels, fontsize=10)

    # Separator lines: human | personas | mixture
    ax.axhline(0.5, color="white", linewidth=2.5)
    ax.axhline(n_rows - 1.5, color="white", linewidth=2.5)

    # Annotate cells
    for i in range(n_rows):
        for j in range(len(SCENARIO_ORDER)):
            val = matrix[i, j]
            text_color = "white" if val < 25 or val > 80 else "black"
            ax.text(j, i, f"{val:.0f}%", ha="center", va="center",
                    fontsize=8, color=text_color, fontweight="bold")

    # Gold standard urgency label below x-axis
    urgency_labels = {0: "Self-care", 1: "Routine GP", 2: "Urgent PC", 3: "A&E", 4: "Ambulance"}
    urgency_colors = {0: "#2ecc71", 1: "#27ae60", 2: "#f39c12", 3: "#e67e22", 4: "#e74c3c"}
    for j, scenario in enumerate(SCENARIO_ORDER):
        u = GOLD_URGENCY[scenario]
        ax.text(j, n_rows - 0.85, urgency_labels[u],
                ha="center", va="bottom", fontsize=6.5,
                color=urgency_colors[u], style="italic",
                transform=ax.get_xaxis_transform())

    cbar = fig.colorbar(im, ax=ax, fraction=0.015, pad=0.02)
    cbar.set_label("Accuracy (%)", fontsize=9)

    ax.set_title("Disposition accuracy per scenario and persona  (green = correct, red = incorrect)",
                 fontsize=11, pad=16)
    plt.subplots_adjust(bottom=0.18, top=0.92, left=0.12, right=0.96)
    out = FIGURES_DIR / "fig2_heatmap.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")

# ---------------------------------------------------------------------------
# Figure 3: Error direction — over vs under escalation
# ---------------------------------------------------------------------------

def fig_error_direction(data):
    """
    For each persona, break errors into:
      - Under-escalation (predicted urgency < gold)
      - Correct
      - Over-escalation (predicted urgency > gold)
    """
    persona_labels = [p[0] for p in PERSONAS]
    under, correct, over = [], [], []

    for label, fname, color in PERSONAS:
        runs = data[label]
        n = len(runs)
        u = sum(1 for r in runs if r["urgency_predicted"] < r["gold_urgency"]) / n * 100
        c = sum(1 for r in runs if r["urgency_correct"]) / n * 100
        o = sum(1 for r in runs if r["urgency_predicted"] > r["gold_urgency"]) / n * 100
        under.append(u)
        correct.append(c)
        over.append(o)

    x = np.arange(len(persona_labels))
    width = 0.55

    fig, ax = plt.subplots(figsize=(9, 5))
    b1 = ax.bar(x, correct, width, label="Correct", color="#2ecc71", zorder=3)
    b2 = ax.bar(x, over,    width, label="Over-escalation", color="#e74c3c",
                bottom=correct, zorder=3)
    b3 = ax.bar(x, under,   width, label="Under-escalation", color="#3498db",
                bottom=[c + o for c, o in zip(correct, over)], zorder=3)

    # Human reference line
    ax.axhline(HUMAN_ACCURACY, color="grey", linewidth=1.5, linestyle="--",
               label=f"Human accuracy ~{HUMAN_ACCURACY:.0f}%", zorder=2)

    ax.set_xticks(x)
    ax.set_xticklabels(persona_labels, fontsize=10)
    ax.set_ylabel("Proportion of runs (%)", fontsize=11)
    ax.set_title("Error direction by persona\n(over-escalation = too urgent; under-escalation = not urgent enough)",
                 fontsize=11, pad=12)
    ax.set_ylim(0, 100)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9, loc="upper right")

    plt.tight_layout()
    out = FIGURES_DIR / "fig3_error_direction.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")

# ---------------------------------------------------------------------------
# Figure 4: Personas vs human data — scenario profile
# ---------------------------------------------------------------------------

def fig_scenario_profiles(data):
    """
    Line plot of accuracy per scenario for each persona + human baseline.
    Shows the bimodal pattern in simulated patients vs graded human responses.
    """
    # Approximate human per-scenario accuracy from Bean et al. clean_examples.csv
    # averaged across all 4 treatment conditions
    human_per_scenario = {
        "Subarachnoid Haemorrhage": (18+32+20+13) / (49+66+60+61) * 100,
        "Pulmonary Embolism":       (4+9+14+10) / (43+63+75+59) * 100,
        "Tinnitus":                 (47+68+54+59) / (54+78+61+69) * 100,
        "Ulcerative Colitis":       (47+30+33+39) / (71+56+57+63) * 100,
        "Renal Colic":              (23+26+13+19) / (62+56+52+58) * 100,
        "Gallstones":               (33+23+35+33) / (64+61+59+63) * 100,
        "Pneumonia":                (5+9+4+3) / (57+76+63+60) * 100,
        "Anaemia":                  (37+30+17+17) / (85+66+58+66) * 100,
        "Common Cold":              (23+17+26+26) / (66+46+60+58) * 100,
        "Allergic Rhinitis":        (28+18+38+31) / (49+32+55+43) * 100,
    }

    fig, ax = plt.subplots(figsize=(13, 5))
    x = np.arange(len(SCENARIO_ORDER))

    # Human line — thicker, grey, plotted first
    human_vals = [human_per_scenario[s] for s in SCENARIO_ORDER]
    ax.plot(x, human_vals, color="black", linewidth=2.5, linestyle="-",
            marker="D", markersize=7, label="Human participants", zorder=5)

    # Standard persona — highlighted
    std_psa = per_scenario_accuracy(data["Standard"])
    std_vals = [std_psa.get(s, 0) for s in SCENARIO_ORDER]
    ax.plot(x, std_vals, color="#4878CF", linewidth=2, linestyle="--",
            marker="o", markersize=6, label="Standard (simulated)", zorder=4)

    # Biased personas — lighter
    for label, fname, color in PERSONAS[1:]:
        psa = per_scenario_accuracy(data[label])
        vals = [psa.get(s, 0) for s in SCENARIO_ORDER]
        ax.plot(x, vals, color=color, linewidth=1.3, linestyle=":",
                marker="o", markersize=4, label=label, alpha=0.85, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels([SCENARIO_SHORT[s] for s in SCENARIO_ORDER], fontsize=8.5)
    ax.set_ylabel("Disposition accuracy (%)", fontsize=11)
    ax.set_ylim(-5, 105)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title("Per-scenario accuracy: human participants vs simulated patient personas",
                 fontsize=11, pad=12)

    # Urgency colour band at top
    urgency_colors = {0: "#2ecc71", 1: "#27ae60", 2: "#f39c12", 3: "#e67e22", 4: "#e74c3c"}
    for j, scenario in enumerate(SCENARIO_ORDER):
        u = GOLD_URGENCY[scenario]
        ax.axvspan(j - 0.5, j + 0.5, alpha=0.06, color=urgency_colors[u], zorder=0)

    ax.legend(fontsize=8.5, loc="upper right", ncol=2)
    plt.tight_layout()
    out = FIGURES_DIR / "fig4_scenario_profiles.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")

# ---------------------------------------------------------------------------
# Figure 5: V1 vs V2 paired comparison
# ---------------------------------------------------------------------------

def fig_v1_v2_comparison(data):
    """
    Grouped bar chart: for each persona, show v1 (solid) vs v2 (hatched) accuracy.
    Human baseline band shown for reference.
    Only includes pairs where v2 data is available.
    """
    available_pairs = [(v1, v2) for v1, v2 in PERSONA_PAIRS if v2 in data]
    if not available_pairs:
        print("Skipping fig5: no v2 data loaded yet.")
        return

    short_names = {
        "Anchorer":               "Anchorer",
        "Dismisser":              "Dismisser",
        "Premature Closer":       "Premature\nCloser",
        "Confidence Deferrer":    "Confidence\nDeferrer",
        "Anxious Catastrophiser": "Catastrophiser",
    }
    color_map = {p[0]: p[2] for p in PERSONAS}

    n_pairs = len(available_pairs)
    x = np.arange(n_pairs)
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))

    v1_accs, v2_accs = [], []
    v1_lo, v1_hi, v2_lo, v2_hi = [], [], [], []

    for v1_label, v2_label in available_pairs:
        r1 = data[v1_label]
        c1 = sum(1 for r in r1 if r["urgency_correct"])
        a1 = c1 / len(r1) * 100
        lo1, hi1 = wilson_ci(c1, len(r1))
        v1_accs.append(a1)
        v1_lo.append(a1 - lo1 * 100)
        v1_hi.append(hi1 * 100 - a1)

        r2 = data[v2_label]
        c2 = sum(1 for r in r2 if r["urgency_correct"])
        a2 = c2 / len(r2) * 100
        lo2, hi2 = wilson_ci(c2, len(r2))
        v2_accs.append(a2)
        v2_lo.append(a2 - lo2 * 100)
        v2_hi.append(hi2 * 100 - a2)

    colors = [color_map[v1] for v1, _ in available_pairs]

    bars1 = ax.bar(x - width / 2, v1_accs, width, color=colors, zorder=3,
                   yerr=[v1_lo, v1_hi], capsize=4,
                   error_kw={"elinewidth": 1.2, "ecolor": "#333"}, label="V1 (original)")
    bars2 = ax.bar(x + width / 2, v2_accs, width, color=colors, zorder=3,
                   yerr=[v2_lo, v2_hi], capsize=4,
                   error_kw={"elinewidth": 1.2, "ecolor": "#333"}, label="V2 (graded)",
                   hatch="///", alpha=0.75)

    ax.axhspan(41.7, 44.2, alpha=0.15, color="grey", zorder=0)
    ax.axhline(HUMAN_ACCURACY, color="grey", linewidth=1.5, linestyle="--", zorder=2,
               label=f"Human baseline ~{HUMAN_ACCURACY:.0f}%")

    for bar, acc in zip(bars1, v1_accs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{acc:.0f}%", ha="center", va="bottom", fontsize=8)
    for bar, acc in zip(bars2, v2_accs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{acc:.0f}%", ha="center", va="bottom", fontsize=8)

    n_note = "n=25 for Catastrophiser v2; n=3 (preliminary) for others"
    ax.set_xticks(x)
    ax.set_xticklabels([short_names[v1] for v1, _ in available_pairs], fontsize=10)
    ax.set_ylabel("Disposition accuracy (%)", fontsize=11)
    ax.set_title(f"V1 vs V2 persona comparison\n({n_note})", fontsize=11, pad=12)
    ax.set_ylim(0, 85)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=9)

    plt.tight_layout()
    out = FIGURES_DIR / "fig5_v1_v2_comparison.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Run all figures
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Loading data...")
    data = load_all()

    print("Generating figures...")
    fig_overall_accuracy(data)
    fig_heatmap(data)
    fig_error_direction(data)
    fig_scenario_profiles(data)
    fig_v1_v2_comparison(data)

    print(f"\nAll figures saved to {FIGURES_DIR}")
