"""
Microgrid IIoT + Agentic AI Platform — Architecture Diagram
Generates system_diagram.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from matplotlib.lines import Line2D

# ── Palette (matches dashboard) ───────────────────────────────────────────────
BLUE        = "#0A6EBD"
BLUE_LIGHT  = "#D6EAF8"
BLUE_MID    = "#3498DB"
GREEN       = "#1A7A4A"
GREEN_LIGHT = "#D5F5E3"
GREEN_MID   = "#27AE60"
AMBER       = "#CA6F1E"
AMBER_LIGHT = "#FDEBD0"
AMBER_MID   = "#E67E22"
RED_LIGHT   = "#FADBD8"
RED_MID     = "#E74C3C"
PURPLE      = "#6C3483"
PURPLE_LIGHT= "#E8DAEF"
TEAL        = "#117A65"
TEAL_LIGHT  = "#D1F2EB"
DARK        = "#1A252F"
MID         = "#566573"
GREY        = "#F2F3F4"
BORDER      = "#BDC3C7"

FIG_W, FIG_H = 24, 14
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis("off")
fig.patch.set_facecolor("#FFFFFF")

# ── Helpers ───────────────────────────────────────────────────────────────────
def tier_bg(x, y, w, h, color, label, label_color=DARK):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.05",
        linewidth=1.2, edgecolor=BORDER,
        facecolor=color, zorder=1
    ))
    ax.text(x + w/2, y + h - 0.35, label,
            ha="center", va="top",
            fontsize=7.5, fontweight="bold",
            color=label_color, zorder=3,
            fontfamily="DejaVu Sans")

def box(x, y, w, h, label, sublabel="", fc="#FFFFFF", ec=BLUE, lw=1.4, fs=8):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.08",
        linewidth=lw, edgecolor=ec,
        facecolor=fc, zorder=4
    ))
    ty = y + h/2 + (0.12 if sublabel else 0)
    ax.text(x + w/2, ty, label,
            ha="center", va="center",
            fontsize=fs, fontweight="bold", color=DARK, zorder=5)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.22, sublabel,
                ha="center", va="center",
                fontsize=6.2, color=MID, zorder=5)

def arrow(x1, y1, x2, y2, label="", color=BLUE_MID, lw=1.5, style="->"):
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle=style, color=color,
                        lw=lw, connectionstyle="arc3,rad=0.0"),
        zorder=6)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my + 0.13, label,
                ha="center", va="bottom",
                fontsize=5.8, color=color,
                bbox=dict(fc="white", ec="none", pad=1), zorder=7)

def curved_arrow(x1, y1, x2, y2, label="", color=BLUE_MID, lw=1.5, rad=0.2):
    ax.annotate("",
        xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="->", color=color,
                        lw=lw, connectionstyle=f"arc3,rad={rad}"),
        zorder=6)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2 + abs(rad)*1.2
        ax.text(mx, my, label,
                ha="center", va="bottom",
                fontsize=5.8, color=color,
                bbox=dict(fc="white", ec="none", pad=1), zorder=7)

# ═══════════════════════════════════════════════════════════════════════════════
# TITLE
# ═══════════════════════════════════════════════════════════════════════════════
ax.text(FIG_W/2, FIG_H - 0.3,
        "Microgrid IIoT + Agentic AI Platform",
        ha="center", va="top",
        fontsize=15, fontweight="bold", color=DARK)
ax.text(FIG_W/2, FIG_H - 0.75,
        "tinylab.ai  ·  Amplified Engineering  ·  GCP australia-southeast1",
        ha="center", va="top",
        fontsize=8.5, color=MID)

# ═══════════════════════════════════════════════════════════════════════════════
# TIER BACKGROUNDS  (x, y, w, h)
# Columns:  Edge | GCP VM | Pub/Sub | BigQuery+ML | AI Agents | Presentation
# ═══════════════════════════════════════════════════════════════════════════════
TIER_Y   = 0.6
TIER_H   = FIG_H - 1.6
PAD      = 0.15

tiers = [
    (0.2,   TIER_Y, 3.2,  TIER_H, AMBER_LIGHT,  "① EDGE"),
    (3.55,  TIER_Y, 3.4,  TIER_H, BLUE_LIGHT,   "② GCP VM  ·  INGEST"),
    (7.1,   TIER_Y, 3.2,  TIER_H, TEAL_LIGHT,   "③ PUB/SUB  ·  MESSAGING"),
    (10.45, TIER_Y, 3.8,  TIER_H, GREEN_LIGHT,  "④ STORAGE  ·  ML"),
    (14.4,  TIER_Y, 4.6,  TIER_H, PURPLE_LIGHT, "⑤ AI AGENT LAYER"),
    (19.15, TIER_Y, 4.55, TIER_H, BLUE_LIGHT,   "⑥ PRESENTATION"),
]
for args in tiers:
    tier_bg(*args)

# ═══════════════════════════════════════════════════════════════════════════════
# ① EDGE
# ═══════════════════════════════════════════════════════════════════════════════
box(0.35, 9.2,  2.9, 1.0, "Docker Compose",  "sim_site.py × 11 containers", fc=AMBER_LIGHT, ec=AMBER_MID)
box(0.35, 7.9,  2.9, 0.9, "site-01 … site-11", "10s interval · TLS 8883",   fc="#FFF", ec=AMBER_MID, fs=7.5)
box(0.35, 6.6,  2.9, 0.9, "nodeMINI / nodeG5", "hw-node-01 · Victron Modbus",fc="#FFF", ec=AMBER_MID, fs=7.5)
box(0.35, 5.5,  2.9, 0.75,"db2mqtt_microgrid.py","SQLite dataout.db → MQTT", fc="#FFF", ec=AMBER, fs=7)
box(0.35, 4.2,  2.9, 0.9, "generate_historical.py","Training data generator", fc="#FFF", ec=AMBER, fs=7)
box(0.35, 3.0,  2.9, 0.9, "historical_data.csv",  "1.8 MB · 24h synthetic",  fc="#FFF", ec=AMBER, fs=7)

# ═══════════════════════════════════════════════════════════════════════════════
# ② GCP VM  (microgrid-broker · e2-small · 34.87.254.184)
# ═══════════════════════════════════════════════════════════════════════════════
box(3.65, 9.2,  3.2, 1.0, "Mosquitto Broker",  "Port 8883 · TLS · per-device auth", fc=BLUE_LIGHT, ec=BLUE)
box(3.65, 7.9,  3.2, 0.9, "mqtt_to_pubsub.py", "systemd · schema validate",          fc="#FFF",      ec=BLUE, fs=7.5)
box(3.65, 6.6,  3.2, 0.9, "Redis Cache",        "live fleet state · TTL 120s",        fc="#FFF",      ec=BLUE_MID, fs=7.5)
box(3.65, 5.3,  3.2, 0.9, "Streamlit App",      "port 8501 · dashboard_app.py",       fc="#FFF",      ec=BLUE_MID, fs=7.5)
box(3.65, 3.0,  3.2, 0.85,"microgrid-broker",   "e2-small · australia-southeast1-a",  fc=BLUE_LIGHT,  ec=BLUE, fs=7)

# ═══════════════════════════════════════════════════════════════════════════════
# ③ PUB/SUB
# ═══════════════════════════════════════════════════════════════════════════════
box(7.2,  9.2,  3.0, 1.0, "microgrid-telemetry", "raw telemetry · all sites",          fc=TEAL_LIGHT, ec=TEAL)
box(7.2,  7.5,  3.0, 1.0, "microgrid-anomalies",  "IF score + telemetry snapshot",      fc=TEAL_LIGHT, ec=TEAL)
box(7.2,  5.8,  3.0, 1.0, "microgrid-agent-events","triage_complete events",            fc=TEAL_LIGHT, ec=TEAL)
box(7.2,  3.7,  3.0, 0.85,"Subscriptions",
    "bq-ingest · anomaly-trigger\ntriage-trigger · dashboard-events", fc="#FFF", ec=TEAL, fs=7)

# ═══════════════════════════════════════════════════════════════════════════════
# ④ STORAGE + ML
# ═══════════════════════════════════════════════════════════════════════════════
box(10.55, 9.2,  3.6, 1.0, "microgrid_telemetry",  "BigQuery · 17 cols · ~50k rows",    fc=GREEN_LIGHT, ec=GREEN)
box(10.55, 7.9,  3.6, 0.9, "anomaly_events",        "BigQuery · score + NL summary",     fc=GREEN_LIGHT, ec=GREEN)
box(10.55, 6.5,  3.6, 1.0, "Isolation Forest",      "sklearn · 200 trees · contam=0.05\n16 features (12 raw + 4 derived)", fc="#FFF", ec=GREEN_MID, fs=7.5)
box(10.55, 5.2,  3.6, 0.9, "anomaly-detector",      "Cloud Run · POST /score /pubsub",   fc="#FFF",      ec=GREEN_MID, fs=7.5)
box(10.55, 3.8,  3.6, 0.9, "microgrid-ml-artefacts","GCS · isolation_forest.joblib",     fc=GREEN_LIGHT, ec=GREEN, fs=7.5)
box(10.55, 2.7,  3.6, 0.8, "Vertex AI Workbench",   "microgrid-anomaly-detection-nb",    fc=GREEN_LIGHT, ec=GREEN, fs=7)

# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ AI AGENT LAYER
# ═══════════════════════════════════════════════════════════════════════════════
box(14.5,  9.2,  4.4, 1.0, "triage-agent",          "Cloud Run · 2 vCPU / 1GB",         fc=PURPLE_LIGHT, ec=PURPLE)
box(14.5,  7.9,  4.4, 1.0, "LangGraph Graph",
    "fetch_context → classify_fault\n→ persist_results → END",                           fc="#FFF",       ec=PURPLE, fs=7.5)
box(14.5,  6.5,  4.4, 1.0, "Claude Sonnet",          "claude-sonnet-4-6\nAnthropics API · fault classification", fc="#FFF", ec=PURPLE, fs=7.5)
box(14.5,  5.2,  4.4, 0.9, "BQ Context Fetch",       "30-min window per site",           fc="#FFF",       ec=PURPLE, fs=7.5)
box(14.5,  4.0,  4.4, 0.9, "Secret Manager",         "anthropic-api-key",                fc=PURPLE_LIGHT, ec=PURPLE, fs=7.5)
box(14.5,  2.7,  4.4, 0.9, "Sprint 3 →",
    "Dispatch Agent · Operator Chat\nForecast Agent · Human-in-loop",                    fc="#FFF",       ec=PURPLE, fs=7, lw=1, )

# ═══════════════════════════════════════════════════════════════════════════════
# ⑥ PRESENTATION
# ═══════════════════════════════════════════════════════════════════════════════
box(19.25, 9.2,  4.3, 1.0, "Fleet Overview",        "KPIs · SOC table · Solar/Load bar",  fc=BLUE_LIGHT, ec=BLUE)
box(19.25, 7.9,  4.3, 1.0, "Site Details",           "SOC gauge · trends · anomaly log",   fc=BLUE_LIGHT, ec=BLUE)
box(19.25, 6.6,  4.3, 1.0, "Anomaly Monitor",        "Timeline · histogram · severity",    fc=BLUE_LIGHT, ec=BLUE)
box(19.25, 5.3,  4.3, 0.9, "AI Agent Pulse",         "Sidebar strobe · triage activity",   fc=PURPLE_LIGHT, ec=PURPLE, fs=7.5)
box(19.25, 4.0,  4.3, 0.9, "Settings",               "ML threshold · infra info",          fc="#FFF",     ec=BLUE_MID, fs=7.5)
box(19.25, 2.7,  4.3, 0.9, "streamlit run dashboard_app.py", "port 8501 · 30s auto-refresh", fc=BLUE_LIGHT, ec=BLUE, fs=7)

# ═══════════════════════════════════════════════════════════════════════════════
# ARROWS  — primary data flow
# ═══════════════════════════════════════════════════════════════════════════════
# Edge → MQTT → VM Broker
arrow(3.25, 9.7,  3.65, 9.7,  "MQTT TLS\n8883",      AMBER_MID, lw=2)
arrow(3.25, 7.35, 3.65, 7.35, "MQTT TLS\n8883",      AMBER_MID, lw=2)

# VM → Pub/Sub: telemetry
arrow(6.85, 9.5,  7.2,  9.7,  "publish",             TEAL, lw=2)

# Pub/Sub telemetry → BQ (bq-ingest-sub)
arrow(10.2, 9.7,  10.55, 9.7, "bq-ingest-sub\npush", GREEN, lw=2)

# Pub/Sub telemetry → anomaly-detector (anomaly-trigger-sub)
arrow(10.2, 9.4,  10.55, 5.65, "anomaly-trigger-sub", GREEN_MID, lw=1.5, style="->")

# anomaly-detector → anomaly_events BQ
arrow(12.35, 5.65, 12.35, 8.35, "INSERT\nanomaly row",  GREEN_MID, lw=1.5)

# anomaly-detector → microgrid-anomalies Pub/Sub
arrow(10.55, 5.65, 8.7,  8.0,  "publish\nanomaly",     TEAL, lw=1.8)

# microgrid-anomalies → triage-agent (triage-trigger-sub)
arrow(10.2,  7.95, 14.5,  9.5,  "triage-trigger-sub", PURPLE, lw=2)

# triage-agent → Claude API (external)
ax.annotate("", xy=(19.1, 7.0), xytext=(18.9, 7.0),
            arrowprops=dict(arrowstyle="->", color=PURPLE, lw=1.5), zorder=6)
ax.text(16.8, 6.9, "Anthropic API\nclaude-sonnet-4-6",
        ha="center", va="top", fontsize=6, color=PURPLE,
        bbox=dict(fc="white", ec=PURPLE, pad=2, lw=0.8), zorder=7)

# triage-agent → anomaly_events UPDATE
curved_arrow(14.5, 9.5, 14.15, 8.35, "INSERT\nenriched row", PURPLE, lw=1.5, rad=-0.3)

# triage-agent → microgrid-agent-events
arrow(14.5, 9.3,  10.2,  6.3,  "publish\ntriage_complete", PURPLE, lw=1.5)

# microgrid-agent-events → Streamlit
arrow(10.2, 6.3,  19.25, 5.75, "agent pulse\npoll", PURPLE, lw=1.5)

# anomaly_events → Streamlit
curved_arrow(14.15, 8.35, 19.25, 8.4, "anomaly\nfeed", GREEN_MID, lw=1.5, rad=-0.15)

# microgrid_telemetry → Streamlit
curved_arrow(14.15, 9.7, 19.25, 9.7, "fleet +\nsite queries", BLUE_MID, lw=1.5, rad=-0.2)

# GCS → anomaly-detector (model load)
arrow(12.35, 4.25, 12.35, 5.2, "load at\nstartup", GREEN, lw=1.5)

# Vertex AI → GCS
arrow(12.35, 3.1, 12.35, 3.7, "save\nmodel", GREEN, lw=1.5)

# Redis → Streamlit (future operator chat)
curved_arrow(6.85, 5.75, 19.25, 5.4, "live state\n(Sprint 3)", BLUE_MID, lw=1, rad=-0.1)

# ═══════════════════════════════════════════════════════════════════════════════
# LEGEND
# ═══════════════════════════════════════════════════════════════════════════════
legend_items = [
    (AMBER_MID,  "Edge / Hardware"),
    (BLUE,       "GCP VM / Ingest"),
    (TEAL,       "Pub/Sub Messaging"),
    (GREEN,      "Storage / ML"),
    (PURPLE,     "AI Agent Layer"),
    (BLUE_MID,   "Presentation"),
]
lx = 0.35
for i, (color, label) in enumerate(legend_items):
    ax.add_patch(mpatches.Rectangle((lx + i*3.9, 0.15), 0.35, 0.25,
                                     fc=color, ec="none", zorder=5))
    ax.text(lx + i*3.9 + 0.45, 0.27, label,
            va="center", fontsize=7, color=DARK, zorder=5)

ax.text(FIG_W - 0.3, 0.18,
        "Sprint 1–2 complete  ·  Sprint 3 in progress  ·  GCP project: microgrid-demo",
        ha="right", va="bottom", fontsize=6.5, color=MID, style="italic")

# ── Border ────────────────────────────────────────────────────────────────────
ax.add_patch(mpatches.FancyBboxPatch(
    (0.05, 0.05), FIG_W - 0.1, FIG_H - 0.1,
    boxstyle="round,pad=0.1",
    linewidth=2, edgecolor=BLUE, facecolor="none", zorder=0
))

plt.tight_layout(pad=0.3)
out = "/home/stanl/projects/g3cli_GCP_microgrid/system_diagram.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
print(f"Saved: {out}")
