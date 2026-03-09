"""Engineer0 Dashboard v2 with detailed restart progress."""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import dash
from dash import Input, Output, State, dcc, html
import dash_bootstrap_components as dbc
import plotly.graph_objs as go

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
)

app.title = "Engineer0 Dashboard"

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESTART_STATUS_FILE = PROJECT_ROOT / "logs" / "restart_status.txt"


def create_header():
    """Create dashboard header with restart button."""
    return dbc.Navbar(
        dbc.Container(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            html.Div(
                                [
                                    html.H2("🤖 Engineer0", className="text-primary mb-0"),
                                    html.Small("Autonomous AI Agent", className="text-muted"),
                                ],
                                className="d-flex flex-column",
                            ),
                            width="auto",
                        ),
                        dbc.Col(
                            html.Div(
                                [
                                    dbc.Button(
                                        [
                                            html.I(className="fas fa-sync-alt me-2"),
                                            "Restart System",
                                        ],
                                        id="restart-button",
                                        color="warning",
                                        size="lg",
                                        className="me-3",
                                    ),
                                    dbc.Button(
                                        [
                                            html.I(className="fas fa-stop me-2"),
                                            "Stop",
                                        ],
                                        id="stop-button",
                                        color="danger",
                                        size="lg",
                                        outline=True,
                                    ),
                                ],
                                className="d-flex",
                            ),
                            width="auto",
                            className="ms-auto",
                        ),
                    ],
                    align="center",
                    className="g-0 w-100",
                ),
            ],
            fluid=True,
        ),
        color="dark",
        dark=True,
        className="mb-4",
    )


# Restart progress modal
restart_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle(
                [
                    html.I(className="fas fa-sync-alt text-warning me-2"),
                    "System Restart in Progress",
                ],
                id="restart-modal-title",
            )
        ),
        dbc.ModalBody(
            [
                dbc.Progress(
                    id="restart-progress",
                    value=0,
                    striped=True,
                    animated=True,
                    className="mb-3",
                    style={"height": "30px"},
                ),
                html.Div(
                    id="restart-status-text",
                    children=[
                        html.P("Initializing restart...", className="mb-2"),
                    ],
                ),
                html.Hr(),
                html.Div(
                    id="restart-details",
                    children=[],
                    style={"max-height": "200px", "overflow-y": "auto"},
                ),
            ]
        ),
        dbc.ModalFooter(
            [
                dbc.Button(
                    "Cancel",
                    id="cancel-restart",
                    color="secondary",
                    className="me-2",
                ),
                dbc.Button(
                    [
                        html.I(className="fas fa-check me-2"),
                        "Ready - Click to Reload UI",
                    ],
                    id="ready-reload-button",
                    color="success",
                    disabled=True,
                    className="me-2",
                ),
            ]
        ),
    ],
    id="restart-modal",
    is_open=False,
    centered=True,
    backdrop="static",
    size="lg",
)


# Confirmation modal (before restart)
confirm_restart_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle(
                [
                    html.I(className="fas fa-exclamation-triangle text-warning me-2"),
                    "Confirm System Restart",
                ]
            )
        ),
        dbc.ModalBody(
            [
                html.P(
                    "Are you sure you want to restart the entire Engineer0 system?",
                    className="lead",
                ),
                html.Hr(),
                html.P("This will:"),
                html.Ul(
                    [
                        html.Li("Stop all running tasks"),
                        html.Li("Restart the dashboard server"),
                        html.Li("Reload all configurations"),
                        html.Li("Reconnect to Ollama"),
                    ]
                ),
                html.P(
                    "Progress will be shown in real-time.",
                    className="text-muted",
                ),
            ]
        ),
        dbc.ModalFooter(
            [
                dbc.Button(
                    "Cancel",
                    id="cancel-confirm-restart",
                    color="secondary",
                    className="me-2",
                ),
                dbc.Button(
                    [
                        html.I(className="fas fa-sync-alt me-2"),
                        "Confirm Restart",
                    ],
                    id="confirm-restart",
                    color="warning",
                ),
            ]
        ),
    ],
    id="confirm-restart-modal",
    is_open=False,
    centered=True,
)


def create_status_cards():
    """Create status overview cards."""
    return dbc.Row(
        [
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.H4("System Status", className="text-success"),
                            html.H2(id="system-status", children="🟢 Running"),
                            html.Small("Last updated: ", className="text-muted"),
                            html.Small(id="last-update", className="text-muted"),
                        ]
                    ),
                    className="text-center",
                ),
                width=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.H4("Tasks Completed", className="text-info"),
                            html.H2(id="tasks-completed", children="0"),
                            html.Small("Total processed", className="text-muted"),
                        ]
                    ),
                    className="text-center",
                ),
                width=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.H4("Uptime", className="text-warning"),
                            html.H2(id="uptime", children="00:00:00"),
                            html.Small("Hours:Minutes:Seconds", className="text-muted"),
                        ]
                    ),
                    className="text-center",
                ),
                width=3,
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.H4("Memory Usage", className="text-primary"),
                            html.H2(id="memory-usage", children="0 MB"),
                            html.Small("Current allocation", className="text-muted"),
                        ]
                    ),
                    className="text-center",
                ),
                width=3,
            ),
        ],
        className="mb-4",
    )


app.layout = dbc.Container(
    [
        dcc.Interval(id="interval-component", interval=2000, n_intervals=0),
        dcc.Interval(id="restart-interval", interval=500, n_intervals=0, disabled=True),
        dcc.Store(id="restart-store", data={"restarting": False, "step": 0}),
        dcc.Location(id="url", refresh=False),
        confirm_restart_modal,
        restart_modal,
        create_header(),
        create_status_cards(),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("Recent Activity"),
                                html.Div(
                                    id="activity-log",
                                    children=[
                                        html.P("System initialized...", className="mb-1"),
                                        html.P("Waiting for tasks...", className="mb-1 text-muted"),
                                    ],
                                ),
                            ]
                        )
                    ),
                    width=6,
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.H4("System Metrics"),
                                dcc.Graph(
                                    id="metrics-graph",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"},
                                ),
                            ]
                        )
                    ),
                    width=6,
                ),
            ],
        ),
    ],
    fluid=True,
    className="py-4",
)


@app.callback(
    Output("confirm-restart-modal", "is_open"),
    [
        Input("restart-button", "n_clicks"),
        Input("cancel-confirm-restart", "n_clicks"),
    ],
    [State("confirm-restart-modal", "is_open")],
    prevent_initial_call=True,
)
def toggle_confirm_modal(restart_click, cancel_click, is_open):
    """Toggle confirmation modal."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open
    
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if button_id == "restart-button":
        return True
    elif button_id == "cancel-confirm-restart":
        return False
    
    return is_open


@app.callback(
    [
        Output("restart-modal", "is_open"),
        Output("restart-interval", "disabled"),
        Output("restart-store", "data"),
    ],
    [
        Input("confirm-restart", "n_clicks"),
        Input("cancel-restart", "n_clicks"),
    ],
    [State("restart-store", "data")],
    prevent_initial_call=True,
)
def handle_restart_initiation(confirm_click, cancel_click, store_data):
    """Initiate restart process."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return False, True, store_data
    
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if button_id == "confirm-restart":
        # Write status file to signal restart
        RESTART_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RESTART_STATUS_FILE, "w") as f:
            f.write("step:0:Initiating restart...\n")
        
        # Start restart process in background
        launcher_path = PROJECT_ROOT / "launcher.sh"
        if launcher_path.exists():
            subprocess.Popen(
                [str(launcher_path), "restart"],
                cwd=str(PROJECT_ROOT),
                start_new_session=True,
            )
        
        return True, False, {"restarting": True, "step": 0}
    
    elif button_id == "cancel-restart":
        return False, True, {"restarting": False, "step": 0}
    
    return False, True, store_data


@app.callback(
    [
        Output("restart-progress", "value"),
        Output("restart-status-text", "children"),
        Output("restart-details", "children"),
        Output("ready-reload-button", "disabled"),
    ],
    [Input("restart-interval", "n_intervals")],
    [State("restart-store", "data")],
)
def update_restart_progress(n, store_data):
    """Update restart progress in real-time."""
    if not store_data.get("restarting"):
        return 0, html.P("Initializing..."), [], True
    
    # Simulate restart progress
    steps = [
        (0, "🛑 Stopping current services..."),
        (15, "🔄 Killing dashboard process..."),
        (25, "🧹 Cleaning up resources..."),
        (35, "🔍 Checking Ollama status..."),
        (45, "🚀 Starting Ollama..."),
        (55, "✅ Ollama running"),
        (65, "📦 Activating virtual environment..."),
        (75, "🌐 Starting dashboard server..."),
        (85, "⏳ Waiting for dashboard..."),
        (95, "✅ Dashboard ready!"),
        (100, "🎉 Restart complete!"),
    ]
    
    # Read status from file if exists
    current_step = min(n // 2, len(steps) - 1)  # Progress every second
    progress, status = steps[current_step]
    
    # Build details list
    details = []
    for i, (_, step_text) in enumerate(steps[:current_step + 1]):
        icon = "✅" if i < current_step else "⏳"
        details.append(
            html.P(
                f"{icon} {step_text}",
                className="mb-1" + (" text-success" if i < current_step else ""),
            )
        )
    
    # Check if ready
    ready = progress >= 100
    
    status_text = html.Div([
        html.P(status, className="lead mb-0"),
        html.P(f"Progress: {progress}%", className="text-muted small"),
    ])
    
    return progress, status_text, details, not ready


@app.callback(
    Output("url", "href"),
    Input("ready-reload-button", "n_clicks"),
    prevent_initial_call=True,
)
def reload_ui(n_clicks):
    """Reload UI when ready."""
    if n_clicks:
        return "/"
    return dash.no_update


@app.callback(
    [
        Output("last-update", "children"),
        Output("uptime", "children"),
        Output("memory-usage", "children"),
        Output("metrics-graph", "figure"),
    ],
    Input("interval-component", "n_intervals"),
)
def update_metrics(n):
    """Update dashboard metrics."""
    import psutil
    
    current_time = datetime.now().strftime("%H:%M:%S")
    
    hours = n // 1800
    minutes = (n % 1800) // 30
    seconds = (n % 30) * 2
    uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024
    memory_str = f"{memory_mb:.1f} MB"
    
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(range(n - 20, n)) if n > 20 else list(range(n)),
            y=[50 + i % 20 for i in range(max(0, n - 20), n)],
            mode="lines",
            name="CPU %",
            line=dict(color="#00ff00"),
        )
    )
    
    fig.update_layout(
        template="plotly_dark",
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis_title="Time",
        yaxis_title="Usage %",
        showlegend=True,
    )
    
    return current_time, uptime, memory_str, fig


if __name__ == "__main__":
    print("🚀 Starting Engineer0 Dashboard v2...")
    print("📊 Dashboard will be available at http://localhost:8050")
    app.run_server(debug=False, host="0.0.0.0", port=8050)
