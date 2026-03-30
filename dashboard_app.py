import time
import os
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

CHAT_AGENT_URL = os.getenv(
    "CHAT_AGENT_URL",
    "https://chat-agent-633335742473.australia-southeast1.run.app"
)
DISPATCH_AGENT_URL = os.getenv(
    "DISPATCH_AGENT_URL",
    "https://dispatch-agent-633335742473.australia-southeast1.run.app"
)

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "microgrid-demo")
DATASET = "microgrid_db"

BLUE        = "#0A6EBD"
BLUE_MID    = "#3498DB"
BLUE_LIGHT  = "#EBF5FB"
GREEN       = "#1A7A4A"
GREEN_MID   = "#27AE60"
GREEN_LIGHT = "#E9F7EF"
AMBER       = "#CA6F1E"
AMBER_MID   = "#E67E22"
AMBER_LIGHT = "#FEF5E7"
RED         = "#B03A2E"
RED_MID     = "#E74C3C"
RED_LIGHT   = "#FDEDEC"
DARK        = "#1A252F"
MID         = "#566573"
GREY        = "#F4F6F7"
BORDER      = "#D5D8DC"

CHART = dict(
    template="plotly_white",
    font=dict(family="Inter, -apple-system, sans-serif", color=DARK),
    plot_bgcolor="white",
    paper_bgcolor="white",
    margin=dict(l=16, r=16, t=40, b=16),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)

st.set_page_config(
    page_title="Microgrid Operations · tinylab.ai",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(f"""
<style>
.stApp, [data-testid="stAppViewContainer"] {{ background: #FFFFFF; }}
[data-testid="stSidebar"] {{ background: {BLUE_LIGHT}; border-right: 1px solid {BORDER}; }}
h1, h2, h3 {{ color: {DARK} !important; }}
h2 {{ border-bottom: 2px solid {BLUE}; padding-bottom: 6px; }}
.kpi {{
    background: #FFF; border: 1px solid {BORDER}; border-top: 3px solid {BLUE};
    border-radius: 6px; padding: 16px 20px 12px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
}}
.kpi-v {{ font-size: 1.9rem; font-weight: 700; color: {BLUE}; line-height: 1.1; }}
.kpi-l {{ font-size: .72rem; color: {MID}; text-transform: uppercase;
          letter-spacing: .05em; margin-top: 4px; }}
.badge {{
    display: inline-block; padding: 2px 9px; border-radius: 12px;
    font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
}}
.bc {{ background: {RED_LIGHT};   color: {RED};   border: 1px solid {RED_MID}; }}
.bh {{ background: {AMBER_LIGHT}; color: {AMBER}; border: 1px solid {AMBER_MID}; }}
.bm {{ background: #FEF9E7; color: #9A7D0A; border: 1px solid #F7DC6F; }}
.bn {{ background: {GREEN_LIGHT}; color: {GREEN}; border: 1px solid {GREEN_MID}; }}
.soc-wrap {{ background: {GREY}; border-radius: 4px; height: 8px; margin: 4px 0; }}
.soc-bar  {{ height: 8px; border-radius: 4px; }}
#MainMenu, footer {{ visibility: hidden; }}
@keyframes pulse {{
    0%   {{ box-shadow: 0 0 0 0 rgba(39,174,96,0.6); opacity: 1; }}
    70%  {{ box-shadow: 0 0 0 8px rgba(39,174,96,0);  opacity: 0.7; }}
    100% {{ box-shadow: 0 0 0 0 rgba(39,174,96,0);  opacity: 1; }}
}}
.agent-dot {{
    width: 11px; height: 11px; border-radius: 50%;
    display: inline-block; margin-right: 7px; vertical-align: middle;
}}
.agent-active {{ background: {GREEN_MID}; animation: pulse 1.6s infinite; }}
.agent-idle   {{ background: #BDC3C7; }}
.agent-panel {{
    background: #FFF; border: 1px solid {BORDER}; border-left: 3px solid {GREEN_MID};
    border-radius: 6px; padding: 10px 12px; font-size: .78rem; margin-top: 4px;
}}
.agent-panel-idle {{
    background: #FAFAFA; border: 1px solid {BORDER}; border-left: 3px solid #BDC3C7;
    border-radius: 6px; padding: 10px 12px; font-size: .78rem; margin-top: 4px; color: {MID};
}}
.chat-tools {{
    font-size: .72rem; color: {MID}; margin-top: 6px;
    padding: 4px 10px; background: {GREY}; border-radius: 4px;
    border-left: 3px solid {BLUE_MID};
}}
.sample-btn-wrap {{ margin-bottom: 12px; }}
@keyframes blink {{
    0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }}
}}
.blink-dot {{
    width: 9px; height: 9px; border-radius: 50%;
    background: {RED_MID}; display: inline-block;
    animation: blink 1.2s infinite; margin-right: 5px; vertical-align: middle;
}}
.ack-card {{
    background: {RED_LIGHT}; border: 1px solid {RED_MID};
    border-left: 4px solid {RED_MID}; border-radius: 6px;
    padding: 9px 11px; margin-top: 6px; font-size: .78rem;
}}
.ack-card-high {{
    background: {AMBER_LIGHT}; border: 1px solid {AMBER_MID};
    border-left: 4px solid {AMBER_MID}; border-radius: 6px;
    padding: 9px 11px; margin-top: 6px; font-size: .78rem;
}}
</style>
""", unsafe_allow_html=True)

# ── BQ client ─────────────────────────────────────────────────────────────────
@st.cache_resource
def get_bq():
    return bigquery.Client(project=PROJECT_ID)

client = get_bq()

@st.cache_data(ttl=30)
def fleet_latest():
    q = f"""
    SELECT * EXCEPT(rn) FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY site_id ORDER BY timestamp DESC) AS rn
        FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
        WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)
    ) WHERE rn = 1 ORDER BY site_id
    """
    df = client.query(q).to_dataframe()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=30)
def site_history(site_id, hours=24):
    q = f"""
    SELECT timestamp, battery_soc, battery_v, solar_w, load_w, power_balance_w,
           inverter_temp, battery_temp, battery_current
    FROM `{PROJECT_ID}.{DATASET}.microgrid_telemetry`
    WHERE site_id = '{site_id}'
      AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
    ORDER BY timestamp ASC
    """
    df = client.query(q).to_dataframe()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

@st.cache_data(ttl=15)
def fetch_agent_activity():
    """Returns (is_active, last_event) — active if triage agent fired in last 5 min."""
    q = f"""
    SELECT site_id, timestamp, fault_type, severity, agent_summary
    FROM `{PROJECT_ID}.{DATASET}.anomaly_events`
    WHERE agent_summary LIKE '[AI Triage]%'
      AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
    ORDER BY timestamp DESC
    LIMIT 1
    """
    try:
        df = client.query(q).to_dataframe()
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return True, df.iloc[0]
    except Exception:
        pass
    return False, None


@st.cache_data(ttl=20)
def fetch_pending_acks():
    """Unacknowledged critical + high alerts requiring operator action."""
    q = f"""
    SELECT a.site_id, a.timestamp, a.fault_type, a.severity, a.anomaly_score, a.agent_summary
    FROM `{PROJECT_ID}.{DATASET}.anomaly_events` a
    LEFT JOIN `{PROJECT_ID}.{DATASET}.ack_events` k
        ON k.site_id = a.site_id
        AND k.anomaly_timestamp = a.timestamp
    WHERE k.site_id IS NULL
      AND a.severity IN ('critical', 'high')
      AND a.agent_summary LIKE '[AI Triage]%'
      AND a.timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
    ORDER BY
        CASE a.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
        a.timestamp DESC
    LIMIT 20
    """
    try:
        df = client.query(q).to_dataframe()
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def fetch_anomalies(site_id=None, limit=300):
    where = f"WHERE site_id = '{site_id}'" if site_id else ""
    q = f"""
    SELECT timestamp, site_id, anomaly_score, fault_type, severity, agent_summary, acknowledged
    FROM `{PROJECT_ID}.{DATASET}.anomaly_events`
    {where}
    ORDER BY timestamp DESC LIMIT {limit}
    """
    df = client.query(q).to_dataframe()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df

# ── Helpers ───────────────────────────────────────────────────────────────────
def kpi(value, label, color=None):
    style = f"color:{color}" if color else ""
    return (f'<div class="kpi">'
            f'<div class="kpi-v" style="{style}">{value}</div>'
            f'<div class="kpi-l">{label}</div></div>')

def soc_color(soc):
    return GREEN_MID if soc > 50 else (AMBER_MID if soc > 20 else RED_MID)

def severity_badge(sev):
    cls = {"critical": "bc", "high": "bh", "medium": "bm"}.get((sev or "").lower(), "bn")
    return f'<span class="badge {cls}">{sev or "normal"}</span>'

def status_badge(soc, has_alarm):
    if has_alarm:
        return '<span class="badge bc">Alarm</span>'
    if soc < 20:
        return '<span class="badge bc">Critical</span>'
    if soc < 40:
        return '<span class="badge bh">Low SOC</span>'
    return '<span class="badge bn">Normal</span>'

def th(label):
    return f'<th style="padding:10px 12px;text-align:left;white-space:nowrap">{label}</th>'

def td(content, extra=""):
    return f'<td style="padding:9px 12px;{extra}">{content}</td>'

def html_table(headers, rows_html):
    ths = "".join(th(h) for h in headers)
    return (f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
            f'background:#FFF;border:1px solid {BORDER};border-radius:8px;overflow:hidden">'
            f'<thead><tr style="background:{BLUE};color:#FFF">{ths}</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>')

TR = f'style="border-bottom:1px solid {BORDER}"'

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"<h2 style='color:{BLUE};border:none;margin-bottom:2px'>⚡ Microgrid Ops</h2>",
                unsafe_allow_html=True)
    st.caption("tinylab.ai · Amplified Engineering")
    st.divider()
    page = st.radio("Navigation",
                    ["Fleet Overview", "Site Details", "Anomaly Monitor",
                     "Operator Chat", "Settings"],
                    label_visibility="collapsed")
    st.divider()
    refresh = st.select_slider("Auto-refresh (s)", [15, 30, 60, 120, 300], value=30)
    anomaly_threshold = st.slider("Anomaly sensitivity", 0.01, 0.20, 0.05, 0.01,
                                  help="Isolation Forest contamination parameter")
    st.divider()
    st.markdown("**AI Agent Status**")
    is_active, last_event = fetch_agent_activity()
    if is_active:
        st.markdown(
            f'<div class="agent-panel">'
            f'<span class="agent-dot agent-active"></span>'
            f'<strong style="color:{GREEN}">Triage Agent Active</strong><br>'
            f'<span style="color:{MID}">{last_event["site_id"]} &nbsp;·&nbsp; '
            f'{last_event["timestamp"].strftime("%H:%M:%S")}</span><br>'
            f'<span style="color:{DARK}">{last_event["fault_type"].upper()}'
            f' &nbsp;·&nbsp; {last_event["severity"]}</span><br>'
            f'<span style="color:{MID};font-size:.73rem">'
            f'{last_event["agent_summary"][:120]}…</span>'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="agent-panel-idle">'
            f'<span class="agent-dot agent-idle"></span>'
            f'<strong>Triage Agent Idle</strong><br>'
            f'<span>Monitoring — no events in last 5 min</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── ACK gate — one alert at a time in sidebar ──────────────────────────
    if "local_acks" not in st.session_state:
        st.session_state.local_acks = set()

    pending_acks = fetch_pending_acks()
    # Filter out locally-acknowledged items — BQ streaming buffer may lag a few seconds
    if not pending_acks.empty and st.session_state.local_acks:
        pending_acks = pending_acks[
            ~pending_acks.apply(
                lambda r: (r["site_id"], r["timestamp"].isoformat()) in st.session_state.local_acks,
                axis=1
            )
        ]

    if not pending_acks.empty:
        total = len(pending_acks)
        top   = pending_acks.iloc[0]
        sev   = top["severity"]
        card_cls  = "ack-card" if sev == "critical" else "ack-card-high"
        sev_color = RED if sev == "critical" else AMBER
        ts_str    = top["timestamp"].strftime("%H:%M UTC")
        summary   = str(top["agent_summary"]).replace("[AI Triage] ", "")[:100]
        count_tag = f" &nbsp;<span style='color:{MID};font-weight:400'>({total})</span>" if total > 1 else ""

        st.divider()
        st.markdown(
            f'<div class="ack-section-title" style="font-size:.75rem;font-weight:700;'
            f'color:{sev_color};text-transform:uppercase;letter-spacing:.05em">'
            f'<span class="blink-dot"></span>Pending ACK{count_tag}</div>'
            f'<div class="{card_cls}">'
            f'<strong style="color:{sev_color}">{sev.upper()}</strong> &nbsp;·&nbsp; '
            f'<strong>{top["fault_type"].replace("_"," ").title()}</strong><br>'
            f'<span style="color:{MID}">{top["site_id"]} &nbsp;·&nbsp; {ts_str}</span><br>'
            f'<span style="color:{DARK};font-size:.73rem;line-height:1.4">{summary}…</span>'
            f'</div>',
            unsafe_allow_html=True
        )
        if st.button("✓ Acknowledge", key=f"ack_{top['site_id']}_{ts_str}",
                     type="primary", use_container_width=True):
            try:
                resp = requests.post(
                    f"{DISPATCH_AGENT_URL}/ack",
                    json={
                        "site_id":       top["site_id"],
                        "timestamp":     top["timestamp"].isoformat(),
                        "fault_type":    top["fault_type"],
                        "severity":      sev,
                        "agent_summary": str(top["agent_summary"])
                    },
                    timeout=20
                )
                data = resp.json()
                if data.get("status") == "acknowledged":
                    st.session_state.local_acks.add(
                        (top["site_id"], top["timestamp"].isoformat())
                    )
                    st.success("Acknowledged ✓")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"ACK failed: {data}")
            except Exception as e:
                st.error(f"Agent unreachable: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# Fleet Overview
# ══════════════════════════════════════════════════════════════════════════════
if page == "Fleet Overview":
    st.markdown("## Fleet Overview")

    df = fleet_latest()
    an = fetch_anomalies(limit=500)

    if df.empty:
        st.info("No telemetry received in the last 15 minutes.")
        st.stop()

    active_alarms = (
        an[an["acknowledged"].ne(True)].groupby("site_id").size().to_dict()
        if not an.empty else {}
    )

    solar_kw   = df["solar_w"].sum() / 1000
    load_kw    = df["load_w"].sum() / 1000
    avg_soc    = df["battery_soc"].mean()
    alarm_sites = len(active_alarms)

    c1, c2, c3, c4, c5 = st.columns(5)
    for col, val, lbl, clr in [
        (c1, len(df),             "Active Sites",       BLUE),
        (c2, f"{solar_kw:.1f} kW","Fleet Solar Output", GREEN_MID),
        (c3, f"{load_kw:.1f} kW", "Fleet Load Demand",  AMBER_MID),
        (c4, f"{avg_soc:.0f}%",   "Avg Battery SOC",    soc_color(avg_soc)),
        (c5, alarm_sites,         "Sites with Alarms",  RED_MID if alarm_sites else GREEN_MID),
    ]:
        col.markdown(kpi(val, lbl, clr), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Site status table
    rows = ""
    for _, r in df.sort_values("battery_soc").iterrows():
        soc = r["battery_soc"]
        sc  = soc_color(soc)
        has_alarm = r["site_id"] in active_alarms
        balance = r["power_balance_w"]
        bal_clr = GREEN_MID if balance >= 0 else AMBER_MID
        alarm_n = str(active_alarms.get(r["site_id"], "—")) if has_alarm else "—"
        soc_bar = (f'<div style="display:flex;align-items:center;gap:8px">'
                   f'<div class="soc-wrap" style="flex:1">'
                   f'<div class="soc-bar" style="width:{min(soc,100):.0f}%;background:{sc}"></div></div>'
                   f'<span style="font-weight:600;color:{sc};min-width:36px">{soc:.0f}%</span></div>')
        rows += (f'<tr {TR}>'
                 + td(r["site_id"], f"font-weight:600;color:{DARK}")
                 + td(soc_bar)
                 + td(f"{r['solar_w']:.0f} W", f"color:{GREEN_MID};font-weight:500")
                 + td(f"{r['load_w']:.0f} W", f"color:{AMBER_MID};font-weight:500")
                 + td(f"{balance:+.0f} W", f"color:{bal_clr};font-weight:500")
                 + td(status_badge(soc, has_alarm))
                 + td(alarm_n, f"color:{RED_MID if has_alarm else MID}")
                 + td(r["timestamp"].strftime("%H:%M:%S"), f"color:{MID};font-size:.8rem")
                 + "</tr>")

    st.markdown(html_table(
        ["Site", "Battery SOC", "Solar", "Load", "Balance", "Status", "Alarms", "Last Reading"],
        rows
    ), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Solar vs Load grouped bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Solar Output", x=df["site_id"], y=df["solar_w"],
                         marker_color=GREEN_MID, opacity=0.85))
    fig.add_trace(go.Bar(name="Load Demand",  x=df["site_id"], y=df["load_w"],
                         marker_color=AMBER_MID, opacity=0.85))
    fig.update_layout(**CHART, title="Current Solar Output vs Load Demand — All Sites",
                      barmode="group", xaxis_title="Site", yaxis_title="Power (W)", height=320)
    st.plotly_chart(fig, width='stretch') #use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# Site Details
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Site Details":
    st.markdown("## Site Details")

    df_fleet = fleet_latest()
    if df_fleet.empty:
        st.info("No live data available.")
        st.stop()

    col_sel, col_hrs = st.columns([2, 1])
    with col_sel:
        site = st.selectbox("Select site", sorted(df_fleet["site_id"].tolist()))
    with col_hrs:
        hours = st.selectbox("History window", [3, 6, 12, 24, 48], index=3)

    live = df_fleet[df_fleet["site_id"] == site].iloc[0]
    soc     = live["battery_soc"]
    sc      = soc_color(soc)
    balance = live["power_balance_w"]

    st.markdown("<br>", unsafe_allow_html=True)

    # Live KPI row
    for col, val, lbl, clr in zip(
        st.columns(6),
        [f"{soc:.0f}%", f"{live['battery_v']:.2f} V", f"{live['solar_w']:.0f} W",
         f"{live['load_w']:.0f} W", f"{balance:+.0f} W", f"{live['inverter_temp']:.1f} °C"],
        ["Battery SOC", "Battery Voltage", "Solar Output",
         "Load Demand", "Power Balance", "Inverter Temp"],
        [sc, BLUE, GREEN_MID, AMBER_MID, GREEN_MID if balance >= 0 else RED_MID, BLUE],
    ):
        col.markdown(kpi(val, lbl, clr), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    hist = site_history(site, hours)

    g_col, t_col = st.columns([1, 3])
    with g_col:
        fig_g = go.Figure(go.Indicator(
            mode="gauge+number",
            value=soc,
            number={"suffix": "%", "font": {"size": 42, "color": sc}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": BORDER},
                "bar": {"color": sc, "thickness": 0.28},
                "bgcolor": "white",
                "borderwidth": 1,
                "bordercolor": BORDER,
                "steps": [
                    {"range": [0, 20],  "color": RED_LIGHT},
                    {"range": [20, 50], "color": AMBER_LIGHT},
                    {"range": [50, 100],"color": GREEN_LIGHT},
                ],
                "threshold": {"line": {"color": RED_MID, "width": 2},
                              "thickness": 0.75, "value": 20}
            },
            title={"text": "Battery SOC", "font": {"size": 14, "color": MID}}
        ))
        fig_g.update_layout(paper_bgcolor="white", height=240,
                            margin=dict(l=20, r=20, t=30, b=10))
        st.plotly_chart(fig_g, width='stretch') #use_container_width=True)

    with t_col:
        if not hist.empty:
            fig_soc = go.Figure()
            fig_soc.add_trace(go.Scatter(
                x=hist["timestamp"], y=hist["battery_soc"],
                fill="tozeroy", fillcolor="rgba(10,110,189,0.08)",
                line=dict(color=BLUE, width=2), name="Battery SOC (%)"
            ))
            fig_soc.add_hline(y=20, line_dash="dash", line_color=RED_MID,
                              annotation_text="Low threshold (20%)")
            fig_soc.update_layout(**CHART, title=f"Battery SOC — Last {hours}h",
                                  yaxis_title="SOC (%)", yaxis_range=[0, 105], height=240)
            st.plotly_chart(fig_soc, width='stretch') #use_container_width=True)

    if not hist.empty:
        fig_pwr = go.Figure()
        fig_pwr.add_trace(go.Scatter(
            x=hist["timestamp"], y=hist["solar_w"],
            fill="tozeroy", fillcolor="rgba(39,174,96,0.15)",
            line=dict(color=GREEN_MID, width=2), name="Solar (W)"
        ))
        fig_pwr.add_trace(go.Scatter(
            x=hist["timestamp"], y=hist["load_w"],
            line=dict(color=AMBER_MID, width=2, dash="dot"), name="Load (W)"
        ))
        fig_pwr.update_layout(**CHART, title="Solar Output vs Load Demand",
                              yaxis_title="Power (W)", height=280)
        st.plotly_chart(fig_pwr, width='stretch') #use_container_width=True)

        bal = (hist["solar_w"] - hist["load_w"]).fillna(0)
        surplus = bal.clip(lower=0)
        deficit = bal.clip(upper=0)
        fig_bal = go.Figure()
        fig_bal.add_trace(go.Scatter(
            x=hist["timestamp"], y=surplus,
            fill="tozeroy", fillcolor="rgba(39,174,96,0.25)",
            line=dict(color=GREEN_MID, width=1),
            name="Surplus"
        ))
        fig_bal.add_trace(go.Scatter(
            x=hist["timestamp"], y=deficit,
            fill="tozeroy", fillcolor="rgba(230,126,34,0.25)",
            line=dict(color=AMBER_MID, width=1),
            name="Deficit"
        ))
        fig_bal.add_hline(y=0, line_color=MID, line_width=1)
        fig_bal.update_layout(**CHART, title="Power Balance  (green = surplus  /  amber = deficit)",
                              yaxis_title="W", height=240, showlegend=True)
        st.plotly_chart(fig_bal, width='stretch') #use_container_width=True)

    st.markdown("### Recent Anomalies")
    an = fetch_anomalies(site_id=site, limit=20)
    if not an.empty:
        rows = ""
        for _, r in an.iterrows():
            rows += (f'<tr {TR}>'
                     + td(r["timestamp"].strftime("%Y-%m-%d %H:%M"), f"color:{MID};font-size:.82rem")
                     + td(severity_badge(r["severity"]))
                     + td(r["fault_type"] or "—", f"font-weight:600;color:{DARK}")
                     + td(f"{r['anomaly_score']:.4f}", f"color:{RED_MID};font-weight:600")
                     + td(r["agent_summary"], f"color:{MID};font-size:.8rem")
                     + "</tr>")
        st.markdown(html_table(
            ["Time (UTC)", "Severity", "Fault Type", "Score", "Summary"], rows
        ), unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="badge bn">No anomalies in selected window</span>',
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# Anomaly Monitor
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Anomaly Monitor":
    st.markdown("## Anomaly Monitor")

    an = fetch_anomalies(limit=500)
    if an.empty:
        st.info("No anomaly events recorded yet.")
        st.stop()

    unacked = an[an["acknowledged"].ne(True)]

    c1, c2, c3, c4 = st.columns(4)
    for col, sev, clr in [
        (c1, "critical", RED_MID),
        (c2, "high",     AMBER_MID),
        (c3, "medium",   "#D4AC0D"),
        (c4, None,       BLUE),
    ]:
        n   = len(unacked[unacked["severity"] == sev]) if sev else len(unacked)
        lbl = f"Unacked {sev.title()}" if sev else "Total Unacknowledged"
        col.markdown(kpi(n, lbl, clr), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sel_site = st.selectbox("Filter by site", ["All"] + sorted(an["site_id"].unique().tolist()))
    with fc2:
        sel_sev = st.selectbox("Filter by severity", ["All", "critical", "high", "medium"])
    with fc3:
        show_acked = st.checkbox("Include acknowledged", value=False)

    filtered = an.copy()
    if sel_site != "All":
        filtered = filtered[filtered["site_id"] == sel_site]
    if sel_sev != "All":
        filtered = filtered[filtered["severity"] == sel_sev]
    if not show_acked:
        filtered = filtered[filtered["acknowledged"].ne(True)]

    if filtered.empty:
        st.info("No events match the current filters.")
        st.stop()

    # Timeline scatter
    sev_clr = {"critical": RED_MID, "high": AMBER_MID, "medium": "#D4AC0D", "unknown": BLUE_MID}
    fig_t = go.Figure()
    for sev, clr in sev_clr.items():
        sub = filtered[filtered["severity"] == sev]
        if not sub.empty:
            fig_t.add_trace(go.Scatter(
                x=sub["timestamp"], y=sub["site_id"], mode="markers",
                marker=dict(color=clr, size=10, symbol="circle",
                            line=dict(color="white", width=1)),
                name=sev.title(),
                text=sub["anomaly_score"].round(4).astype(str),
                hovertemplate="<b>%{y}</b><br>%{x}<br>Score: %{text}<extra></extra>"
            ))
    fig_t.update_layout(**CHART, title="Anomaly Timeline by Site",
                        xaxis_title="Time", yaxis_title="",
                        height=320,
                        yaxis=dict(categoryorder="category ascending"))
    st.plotly_chart(fig_t, use_container_width=True)

    h_col, b_col = st.columns(2)
    with h_col:
        fig_h = go.Figure()
        fig_h.add_trace(go.Histogram(x=filtered["anomaly_score"], nbinsx=40,
                                    marker_color=BLUE_MID, opacity=0.8))
        fig_h.update_layout(**CHART, title="Anomaly Score Distribution",
                            xaxis_title="Score (lower = more anomalous)",
                            yaxis_title="Count", height=280, showlegend=False)
        st.plotly_chart(fig_h, use_container_width=True)

    with b_col:
        by_site = (filtered.groupby("site_id").size()
                   .sort_values(ascending=False).reset_index(name="count"))
        fig_b = go.Figure()
        fig_b.add_trace(go.Bar(x=by_site["site_id"], y=by_site["count"],
                               marker_color=BLUE_MID, opacity=0.85))
        fig_b.update_layout(**CHART, title="Anomaly Count per Site",
                            xaxis_title="Site", yaxis_title="Count",
                            height=280, showlegend=False)
        st.plotly_chart(fig_b, use_container_width=True)

    st.markdown(f"**{len(filtered)}** events matching filters")
    rows = ""
    for _, r in filtered.head(100).iterrows():
        rows += (f'<tr {TR}>'
                 + td(r["timestamp"].strftime("%Y-%m-%d %H:%M"),
                      f"color:{MID};font-size:.82rem;white-space:nowrap")
                 + td(r["site_id"], f"font-weight:600;color:{DARK}")
                 + td(severity_badge(r["severity"]))
                 + td(r["fault_type"] or "—")
                 + td(f"{r['anomaly_score']:.4f}", f"color:{RED_MID};font-weight:600")
                 + td(r["agent_summary"], f"color:{MID};font-size:.8rem")
                 + "</tr>")
    st.markdown(html_table(
        ["Time (UTC)", "Site", "Severity", "Fault Type", "Score", "Summary"], rows
    ), unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# Operator Chat
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Operator Chat":
    st.markdown("## Operator Chat")
    st.caption(
        "Ask about site status, recent faults, or fleet health. "
        "Powered by Claude Sonnet with live BigQuery tools."
    )

    if "chat_msgs" not in st.session_state:
        st.session_state.chat_msgs = []

    col_clear, col_info = st.columns([1, 5])
    with col_clear:
        if st.button("Clear", type="secondary"):
            st.session_state.chat_msgs = []
            st.rerun()
    with col_info:
        if st.session_state.chat_msgs:
            st.caption(f"{len(st.session_state.chat_msgs)//2} exchange(s) in session")

    # Sample questions — shown only when no history yet
    if not st.session_state.chat_msgs:
        st.markdown(
            f'<div style="background:{BLUE_LIGHT};border:1px solid {BORDER};'
            f'border-radius:8px;padding:14px 18px;margin-bottom:16px">'
            f'<b style="color:{BLUE}">Suggested questions</b></div>',
            unsafe_allow_html=True
        )
        samples = [
            ("Fleet status",        "What's the current status of all sites in the fleet?"),
            ("Low battery alert",   "Which sites have the lowest battery SOC right now?"),
            ("Recent anomalies",    "Show me the 5 most recent anomaly events across all sites"),
            ("Critical faults",     "Are there any critical or high-severity faults active?"),
            ("Solar vs load",       "How does total solar generation compare to fleet load?"),
            ("Site deep-dive",      "Give me a full diagnostic summary for site-03"),
        ]
        c1, c2, c3 = st.columns(3)
        cols_cycle = [c1, c2, c3]
        for i, (label, q) in enumerate(samples):
            if cols_cycle[i % 3].button(label, key=f"sq_{i}", use_container_width=True):
                st.session_state["_pending_chat"] = q
                st.rerun()

    # Display conversation history
    for msg in st.session_state.chat_msgs:
        avatar = "⚡" if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("tools_used"):
                st.markdown(
                    f'<div class="chat-tools">🔧 Data sources: '
                    f'{", ".join(set(msg["tools_used"]))}</div>',
                    unsafe_allow_html=True
                )

    # Gather input from chat widget or a clicked sample button
    pending = st.session_state.pop("_pending_chat", None)
    prompt = st.chat_input("Ask about your microgrid fleet…") or pending

    if prompt:
        st.session_state.chat_msgs.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="⚡"):
            with st.spinner("Querying fleet data…"):
                try:
                    resp = requests.post(
                        f"{CHAT_AGENT_URL}/chat",
                        json={"messages": [
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.chat_msgs
                        ]},
                        timeout=45
                    )
                    data = resp.json()
                    reply = data.get("response", "No response received.")
                    tools = data.get("tools_used", [])
                except Exception as e:
                    reply = f"⚠️ Could not reach Chat Agent: {e}"
                    tools = []

            st.markdown(reply)
            if tools:
                st.markdown(
                    f'<div class="chat-tools">🔧 Data sources: '
                    f'{", ".join(set(tools))}</div>',
                    unsafe_allow_html=True
                )

        st.session_state.chat_msgs.append({
            "role": "assistant", "content": reply, "tools_used": tools
        })

# ══════════════════════════════════════════════════════════════════════════════
# Settings
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Settings":
    st.markdown("## Settings")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### ML Model")
        st.markdown(f"""
        <div style="background:{BLUE_LIGHT};border:1px solid {BORDER};
                    border-radius:8px;padding:16px;line-height:2">
            <b>Algorithm:</b> Isolation Forest<br>
            <b>Estimators:</b> 200<br>
            <b>Contamination:</b> {anomaly_threshold:.2f} (sidebar slider)<br>
            <b>Features:</b> 16 &nbsp;(12 raw + 4 derived)<br>
            <b>Artefact:</b> gs://microgrid-ml-artefacts/models/2026-03-27/<br>
            <b>Scoring endpoint:</b> Cloud Run anomaly-detector
        </div>""", unsafe_allow_html=True)

    with c2:
        st.markdown("### Infrastructure")
        st.markdown(f"""
        <div style="background:{BLUE_LIGHT};border:1px solid {BORDER};
                    border-radius:8px;padding:16px;line-height:2">
            <b>GCP Project:</b> microgrid-demo<br>
            <b>Region:</b> australia-southeast1<br>
            <b>MQTT Broker:</b> 34.87.254.184:8883 (TLS)<br>
            <b>BigQuery:</b> microgrid_db.microgrid_telemetry<br>
            <b>Pub/Sub:</b> microgrid-telemetry → anomaly-trigger-sub<br>
            <b>Agent layer:</b> Sprint 3 (LangGraph)
        </div>""", unsafe_allow_html=True)

# ── Auto-refresh (disabled on chat page to preserve conversation) ──────────────
if page != "Operator Chat":
    time.sleep(refresh)
    st.rerun()
