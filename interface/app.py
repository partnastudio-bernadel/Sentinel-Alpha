import os
import sys
import json
import uuid
import time
import io
import contextlib
import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv

# Setup path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, ".."))
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.graphs.sentiment_graph import build_sentiment_graph

# ---------------------------------------------------------
# Stdout & Stderr Capture Context Manager
# ---------------------------------------------------------
@contextlib.contextmanager
def capture_stdout_stderr(callback):
    class StreamWrapper:
        def __init__(self, original, cb):
            self.original = original
            self.cb = cb
            self.buf = io.StringIO()
            self.last_update = 0.0

        def write(self, data):
            self.original.write(data)
            self.original.flush()
            self.buf.write(data)
            
            # Rate limit/throttle UI updates (minimum 100ms between updates unless it's a newline)
            current_time = time.time()
            if current_time - self.last_update > 0.1 or "\n" in data:
                self.cb(self.buf.getvalue())
                self.last_update = current_time
            return len(data)

        def flush(self):
            self.original.flush()

        def __getattr__(self, name):
            return getattr(self.original, name)

    stdout_wrapper = StreamWrapper(sys.stdout, callback)
    stderr_wrapper = StreamWrapper(sys.stderr, callback)
    
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    
    sys.stdout = stdout_wrapper
    sys.stderr = stderr_wrapper
    
    try:
        yield stdout_wrapper.buf
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        # Final render to ensure all logs are captured
        callback(stdout_wrapper.buf.getvalue())

# ---------------------------------------------------------
# Page Config & Theming
# ---------------------------------------------------------
st.set_page_config(
    page_title="Sentinel Sentiment",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "theme" not in st.session_state:
    st.session_state.theme = "light"

def toggle_theme():
    st.session_state.theme = "dark" if st.session_state.theme == "light" else "light"

IS_DARK = st.session_state.theme == "dark"

# Apple-inspired premium CSS with Glassmorphism
css = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
    --bg-color: {'#121212' if IS_DARK else '#f5f5f7'};
    --card-bg: {'rgba(30, 30, 32, 0.7)' if IS_DARK else 'rgba(255, 255, 255, 0.7)'};
    --text-primary: {'#f5f5f7' if IS_DARK else '#1d1d1f'};
    --text-secondary: {'#86868b' if IS_DARK else '#86868b'};
    --border-color: {'rgba(255, 255, 255, 0.1)' if IS_DARK else 'rgba(0, 0, 0, 0.05)'};
    --accent-color: #0071e3;
    --success-color: #34c759;
    --warning-color: #ff9f0a;
    --danger-color: #ff3b30;
    --glass-blur: blur(20px);
    --shadow: 0 4px 24px {'rgba(0,0,0,0.4)' if IS_DARK else 'rgba(0,0,0,0.04)'};
}}

html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main {{
    background-color: var(--bg-color) !important;
    color: var(--text-primary) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}}

/* Hide standard elements */
header[data-testid="stHeader"], footer {{ display: none !important; }}

/* Glassmorphic Cards */
.apple-card {{
    background: var(--card-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 24px;
    box-shadow: var(--shadow);
    margin-bottom: 24px;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

/* Node styling */
.node-container {{
    display: flex;
    flex-direction: column;
    gap: 12px;
}}

.node-card {{
    background: var(--card-bg);
    backdrop-filter: var(--glass-blur);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 16px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    transition: all 0.3s ease;
}}

.node-status-pending {{ border-left: 4px solid var(--text-secondary); }}
.node-status-running {{ border-left: 4px solid var(--accent-color); box-shadow: 0 0 15px rgba(0, 113, 227, 0.3); }}
.node-status-completed {{ border-left: 4px solid var(--success-color); }}
.node-status-failed {{ border-left: 4px solid var(--danger-color); }}

.node-title {{
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
}}

.badge {{
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.badge-pending {{ background: rgba(134, 134, 139, 0.15); color: var(--text-secondary); }}
.badge-running {{ background: rgba(0, 113, 227, 0.15); color: var(--accent-color); }}
.badge-completed {{ background: rgba(52, 199, 89, 0.15); color: var(--success-color); }}
.badge-failed {{ background: rgba(255, 59, 48, 0.15); color: var(--danger-color); }}

.metric-value {{
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.5px;
    color: var(--text-primary);
}}
.metric-label {{
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
</style>
""";
st.markdown(css, unsafe_allow_html=True)

# ---------------------------------------------------------
# Sidebar / Controls
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("<h2 style='font-weight:700; letter-spacing:-0.5px;'>Sentinel Dashboard</h2>", unsafe_allow_html=True)
    st.button("Toggle Theme 🌓", on_click=toggle_theme, use_container_width=True)
    st.markdown("---")
    
    ticker = st.text_input("Ticker Symbol", value="AAPL")
    limit = st.slider("Max Articles", min_value=1, max_value=20, value=5)
    force_rescore = st.checkbox("Force Rescore (Bypass Cache)", value=False)
    
    run_btn = st.button("Run Pipeline ▶", type="primary", use_container_width=True)

# ---------------------------------------------------------
# Main Execution Logic
# ---------------------------------------------------------
st.markdown("<h1 style='font-weight:700; letter-spacing:-1px;'>Pipeline Execution Explorer</h1>", unsafe_allow_html=True)

if "graph_states" not in st.session_state:
    st.session_state.graph_states = []
    st.session_state.is_running = False
    st.session_state.final_report = None
    
# Node definitions for the UI sequence
expected_nodes = ["ingest_news", "check_cache", "prepare_bypass", "sentiment_scorer_node", "cio_analyst_node"]

def get_node_badge(status):
    if status == "running": return "<span class='badge badge-running'>Running</span>"
    if status == "completed": return "<span class='badge badge-completed'>Completed</span>"
    if status == "failed": return "<span class='badge badge-failed'>Failed</span>"
    return "<span class='badge badge-pending'>Pending</span>"

if run_btn:
    st.session_state.graph_states = []
    st.session_state.final_report = None
    st.session_state.is_running = True
    
    env_path = os.path.join(sentiment_dir, ".env.local")
    if not os.path.exists(env_path):
        env_path = os.path.join(sentiment_dir, ".env")
    csv_path = os.path.join(sentiment_dir, "data", "financial_sentiment.csv")
    load_dotenv(env_path)
    
    app = build_sentiment_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "env_path": env_path,
            "csv_path": csv_path
        }
    }
    
    current_state = {
        "ticker": ticker.upper().strip(),
        "timeframe_days": 3,
        "limit": limit,
        "force_rescore": force_rescore
    }
    
    # Grid layout for Flow and Live Terminal logs
    col_flow, col_logs = st.columns([5, 7])
    with col_flow:
        flow_placeholder = st.empty()
    with col_logs:
        logs_placeholder = st.empty()
        
    inspector_placeholder = st.empty()
    
    # Render loop helpers
    def render_ui(current_active_node=None, error_node=None):
        with flow_placeholder.container():
            st.markdown("<div class='apple-card' style='height: 480px; display: flex; flex-direction: column;'>", unsafe_allow_html=True)
            st.markdown("<h3 style='margin-top:0; margin-bottom: 12px;'>Live Node Flow</h3>", unsafe_allow_html=True)
            
            st.markdown("<div class='node-container' style='flex-grow: 1; overflow-y: auto;'>", unsafe_allow_html=True)
            # Draw flow
            for node in expected_nodes:
                if node == "prepare_bypass" and not force_rescore: continue
                if node == "check_cache" and force_rescore: continue
                
                # Determine status
                status = "pending"
                has_run = any(s["node"] == node for s in st.session_state.graph_states)
                
                if has_run:
                    status = "completed"
                elif node == current_active_node:
                    status = "running"
                elif node == error_node:
                    status = "failed"
                    
                st.markdown(f"""
                <div class="node-card node-status-{status}" style="margin-bottom: 8px;">
                    <div class="node-title">{node}</div>
                    <div>{get_node_badge(status)}</div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
            
        # Show inspector for last completed node
        if st.session_state.graph_states:
            last_state = st.session_state.graph_states[-1]
            with inspector_placeholder.container():
                st.markdown("<div class='apple-card'>", unsafe_allow_html=True)
                st.markdown(f"<h3 style='margin-top:0;'>Inspector: {last_state['node']}</h3>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Inputs (State Before)**")
                    st.json(last_state["input"], expanded=False)
                with c2:
                    st.markdown("**Outputs (State Updates)**")
                    st.json(last_state["output"], expanded=False)
                st.markdown("</div>", unsafe_allow_html=True)

    def log_callback(logs_text):
        with logs_placeholder.container():
            st.markdown(f"""
            <div style="background: rgba(30, 30, 32, 0.7); backdrop-filter: blur(20px); border: 1px solid var(--border-color); border-radius: 20px; padding: 24px; box-shadow: var(--shadow); height: 480px; display: flex; flex-direction: column;">
                <h3 style="margin-top:0; margin-bottom: 12px; color: var(--text-primary);">Build Progress Logs</h3>
                <div id="log-container" style="background: #18181b; color: #e4e4e7; font-family: 'Courier New', Courier, monospace; padding: 16px; border-radius: 12px; flex-grow: 1; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); font-size: 13px; line-height: 1.5; white-space: pre-wrap;">{logs_text}</div>
            </div>
            <script>
                var objDiv = document.getElementById("log-container");
                if (objDiv) {{
                    objDiv.scrollTop = objDiv.scrollHeight;
                }}
            </script>
            """, unsafe_allow_html=True)

    # Initial Render of elements
    render_ui()
    log_callback("Starting pipeline execution stream...\n")
    
    try:
        with capture_stdout_stderr(log_callback):
            for chunk in app.stream(current_state.copy(), config, stream_mode="updates"):
                for node_name, node_update in chunk.items():
                    render_ui(current_active_node=node_name)
                    # Safely handle Command objects or None to avoid iterable errors
                    output_dict = {}
                    if isinstance(node_update, dict):
                        output_dict = node_update
                    elif hasattr(node_update, "update") and isinstance(getattr(node_update, "update", {}), dict):
                        output_dict = node_update.update
                    
                    # Save execution step
                    step_data = {
                        "node": node_name,
                        "input": dict(current_state),
                        "output": output_dict
                    }
                    st.session_state.graph_states.append(step_data)
                    
                    # Update current state conceptually
                    current_state.update(output_dict)
                    
                    if node_name == "cio_analyst_node" and "results" in node_update:
                        st.session_state.final_report = node_update["results"]
                    
                    # Small delay for UI visualization effect
                    time.sleep(0.5)
                    render_ui() # Re-render as completed

        st.session_state.is_running = False
    except Exception as e:
        render_ui(error_node="Exception Occurred")
        st.error(f"Execution Error: {e}")
        st.session_state.is_running = False

# ---------------------------------------------------------
# Final Scorecard Rendering
# ---------------------------------------------------------
if not st.session_state.is_running and st.session_state.final_report:
    rep = st.session_state.final_report
    
    st.markdown("<h2 style='margin-top: 2rem;'>Analysis Results</h2>", unsafe_allow_html=True)
    st.markdown("<div class='apple-card'>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"<div class='metric-label'>Aggregate Score</div><div class='metric-value'>{rep.get('aggregate_score', 'N/A')}</div>", unsafe_allow_html=True)
    with c2:
        lbl = rep.get('aggregate_label', 'Neutral')
        color_class = "success" if "Positive" in lbl else ("danger" if "Negative" in lbl else "warning")
        st.markdown(f"<div class='metric-label'>Sentiment Label</div><div class='metric-value' style='color: var(--{color_class}-color);'>{lbl}</div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-label'>Articles Analyzed</div><div class='metric-value'>{len(rep.get('articles', []))}</div>", unsafe_allow_html=True)
        
    st.markdown("<hr style='border-color: var(--border-color); margin: 20px 0;'>", unsafe_allow_html=True)
    st.markdown("#### Reasoning")
    st.write(rep.get("reasoning", "No reasoning provided."))
    
    if "compliance_override" in rep:
        co = rep["compliance_override"]
        st.markdown("<hr style='border-color: var(--border-color); margin: 20px 0;'>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color: var(--warning-color);'>⚠️ Compliance Alert: {co.get('limit_violated')}</h4>", unsafe_allow_html=True)
        st.write(co.get("justification", ""))
        st.caption(f"Status: {co.get('status')}")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    if rep.get("articles"):
        st.markdown("### Article Breakdown")
        for art in rep["articles"]:
            lbl = art.get('sentiment_label', 'Neutral')
            color = "var(--success-color)" if "Positive" in lbl else ("var(--danger-color)" if "Negative" in lbl else "var(--warning-color)")
            st.markdown(f"""
            <div style="background: var(--card-bg); padding: 16px; border-radius: 12px; border: 1px solid var(--border-color); margin-bottom: 12px;">
                <strong>{art.get('title')}</strong><br>
                <span style="color: {color}; font-weight: 600; font-size: 14px;">{lbl} (Score: {art.get('sentiment_score')})</span> | 
                <span style="color: var(--text-secondary); font-size: 13px;">Conf: {art.get('confidence')}</span>
                <p style="font-size: 14px; margin-top: 8px;">{art.get('reasoning_summary')}</p>
            </div>
            """, unsafe_allow_html=True)
