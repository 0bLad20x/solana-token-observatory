"""Design system for the diagnostics dashboard.

One place for colour, type and chart styling so every view reads as the same
instrument. The palette is deliberately cold and low-chroma: the data carries
the colour, the interface does not compete with it.
"""

from __future__ import annotations

INK = "#0A0E15"
SURFACE = "#121824"
SURFACE_RAISED = "#18202E"
LINE = "#242F41"
TEXT = "#E7EBF3"
MUTED = "#8B98AE"
FAINT = "#5C687C"

TEAL = "#2FBFA0"      # improvement, life
AMBER = "#F0A83C"     # attention, retirement candidates
ROSE = "#E4595F"      # decay, loss
VIOLET = "#8C7BF0"    # graduation
BLUE = "#4C8DF6"      # neutral highlight

COLORS = {
    "ink": INK,
    "surface": SURFACE,
    "surface_raised": SURFACE_RAISED,
    "line": LINE,
    "text": TEXT,
    "muted": MUTED,
    "faint": FAINT,
    "teal": TEAL,
    "amber": AMBER,
    "rose": ROSE,
    "violet": VIOLET,
    "blue": BLUE,
}

# Sequential density ramp: ink → indigo → plum → ember. Chosen over Viridis so
# that the empty regions of the state space stay visually empty.
DENSITY_SCALE = [
    [0.00, "#101725"],
    [0.12, "#172B4A"],
    [0.30, "#2C4180"],
    [0.50, "#5B4E97"],
    [0.68, "#94608F"],
    [0.84, "#D07E63"],
    [1.00, "#F7CE79"],
]

# Diverging ramp for improvement vs decay.
DIVERGING_SCALE = [
    [0.00, ROSE],
    [0.50, "#2A3446"],
    [1.00, TEAL],
]

# Share ramps used for "how much of this row is X".
SHARE_SCALE = [
    [0.00, "#111826"],
    [0.45, "#274769"],
    [1.00, TEAL],
]

RISK_SCALE = [
    [0.00, "#111826"],
    [0.45, "#6A4426"],
    [1.00, AMBER],
]

ACTIVITY_COLORS = {
    "hot": TEAL,
    "active": "#4FA98F",
    "low": BLUE,
    "idle": "#6E7A92",
    "dead": ROSE,
    "unknown": FAINT,
}

OUTCOME_COLORS = {
    "improved": TEAL,
    "same": BLUE,
    "deteriorated": ROSE,
    "graduated": VIOLET,
    "gone": "#5C687C",
    "unknown": "#3A4557",
}

FONT_UI = "'IBM Plex Sans', system-ui, -apple-system, Segoe UI, sans-serif"
FONT_MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"


def register_template():
    """Register and select the Plotly template. Safe to call more than once."""
    import plotly.graph_objects as go
    import plotly.io as pio

    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT_UI, "size": 12, "color": TEXT},
        title={"font": {"family": FONT_UI, "size": 15, "color": TEXT}, "x": 0, "xanchor": "left"},
        colorway=[TEAL, AMBER, BLUE, VIOLET, ROSE, "#4FA98F", "#C58AA5"],
        margin={"l": 70, "r": 24, "t": 46, "b": 56},
        hoverlabel={
            "bgcolor": SURFACE_RAISED,
            "bordercolor": LINE,
            "font": {"family": FONT_MONO, "size": 12, "color": TEXT},
        },
        legend={
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"size": 11, "color": MUTED},
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        xaxis={
            "gridcolor": "rgba(36,47,65,0.7)",
            "zerolinecolor": LINE,
            "linecolor": LINE,
            "tickfont": {"family": FONT_MONO, "size": 11, "color": MUTED},
            "title": {"font": {"size": 11, "color": MUTED}},
        },
        yaxis={
            "gridcolor": "rgba(36,47,65,0.7)",
            "zerolinecolor": LINE,
            "linecolor": LINE,
            "tickfont": {"family": FONT_MONO, "size": 11, "color": MUTED},
            "title": {"font": {"size": 11, "color": MUTED}},
        },
    )
    pio.templates["jupiter"] = template
    pio.templates.default = "jupiter"
    return template


GRAPH_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
    "toImageButtonOptions": {"format": "png", "scale": 2, "filename": "jupiter_state_space"},
}


INDEX_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600&display=swap" rel="stylesheet">
    <style>
      :root {
        --ink: __INK__;
        --surface: __SURFACE__;
        --raised: __RAISED__;
        --line: __LINE__;
        --text: __TEXT__;
        --muted: __MUTED__;
        --faint: __FAINT__;
        --teal: __TEAL__;
        --amber: __AMBER__;
        --rose: __ROSE__;
        --violet: __VIOLET__;
        --blue: __BLUE__;
        --ui: __FONT_UI__;
        --mono: __FONT_MONO__;
        --radius: 10px;
      }
      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; background: var(--ink); }
      body {
        font-family: var(--ui);
        color: var(--text);
        -webkit-font-smoothing: antialiased;
        background-image:
          radial-gradient(900px 500px at 12% -10%, rgba(76,141,246,0.10), transparent 60%),
          radial-gradient(700px 400px at 92% 0%, rgba(47,191,160,0.07), transparent 55%);
        background-attachment: fixed;
      }
      ::selection { background: rgba(47,191,160,0.28); }

      .shell { display: grid; grid-template-columns: 232px minmax(0, 1fr); min-height: 100vh; }

      /* ---- rail ---------------------------------------------------- */
      .rail {
        border-right: 1px solid var(--line);
        background: linear-gradient(180deg, rgba(18,24,36,0.92), rgba(10,14,21,0.92));
        padding: 20px 14px 28px;
        position: sticky; top: 0; height: 100vh; overflow-y: auto;
      }
      .brand { padding: 0 8px 18px; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
      .brand-mark {
        font-family: 'IBM Plex Sans Condensed', var(--ui);
        font-size: 19px; font-weight: 600; letter-spacing: 0.02em;
      }
      .brand-sub {
        font-family: var(--mono); font-size: 10.5px; color: var(--faint);
        text-transform: uppercase; letter-spacing: 0.14em; margin-top: 4px;
      }
      .rail-group { margin-bottom: 22px; }
      .eyebrow {
        font-family: 'IBM Plex Sans Condensed', var(--ui);
        font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.16em;
        color: var(--faint); margin: 0 0 9px 8px;
      }
      .nav-item {
        display: flex; align-items: baseline; gap: 9px; width: 100%;
        padding: 8px 10px; margin-bottom: 2px;
        border: 1px solid transparent; border-radius: 8px;
        background: transparent; color: var(--muted);
        font-family: var(--ui); font-size: 13px; text-align: left; cursor: pointer;
        transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
      }
      .nav-item:hover { background: rgba(255,255,255,0.035); color: var(--text); }
      .nav-item .phase { font-family: var(--mono); font-size: 10px; color: var(--faint); margin-left: auto; }
      .nav-item.is-active {
        background: rgba(47,191,160,0.10); border-color: rgba(47,191,160,0.34); color: var(--text);
      }
      .nav-item.is-active .phase { color: var(--teal); }

      .field { margin-bottom: 12px; }
      .field > label {
        display: block; font-family: var(--mono); font-size: 10px; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--faint); margin: 0 0 5px 2px;
      }

      /* ---- header -------------------------------------------------- */
      .main { padding: 22px 26px 60px; min-width: 0; }
      .head { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 18px; margin-bottom: 18px; }
      .head h1 {
        font-family: 'IBM Plex Sans Condensed', var(--ui);
        font-size: 26px; font-weight: 600; margin: 0; letter-spacing: 0.01em;
      }
      .head .lede { color: var(--muted); font-size: 13px; margin: 6px 0 0; max-width: 68ch; }
      .stamp { margin-left: auto; text-align: right; font-family: var(--mono); font-size: 11px; color: var(--faint); }

      .chips { display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 18px; }
      .chip {
        border: 1px solid var(--line); background: rgba(24,32,46,0.7); color: var(--muted);
        border-radius: 999px; padding: 6px 13px; font-size: 12px; cursor: pointer;
        font-family: var(--ui); transition: all 120ms ease;
      }
      .chip:hover { color: var(--text); border-color: #33425a; }
      .chip.is-on { border-color: rgba(47,191,160,0.5); color: var(--teal); background: rgba(47,191,160,0.09); }
      .chip.reset { color: var(--faint); }

      /* ---- cards --------------------------------------------------- */
      .grid { display: grid; gap: 14px; }
      .cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      @media (max-width: 1180px) {
        .shell { grid-template-columns: 1fr; }
        .rail { position: static; height: auto; }
        .cols-2, .cols-3, .cols-4 { grid-template-columns: 1fr; }
      }
      .card {
        background: linear-gradient(180deg, rgba(24,32,46,0.86), rgba(18,24,36,0.86));
        border: 1px solid var(--line); border-radius: var(--radius);
        padding: 16px 18px 12px;
      }
      .card.flush { padding: 14px 10px 4px; }
      .card-title {
        font-family: 'IBM Plex Sans Condensed', var(--ui); font-size: 13px;
        text-transform: uppercase; letter-spacing: 0.13em; color: var(--muted); margin: 0 0 2px 6px;
      }
      .card-note { font-size: 12px; color: var(--faint); margin: 0 0 8px 6px; max-width: 90ch; }

      .kpi { padding: 14px 16px; }
      .kpi .k-label {
        font-family: var(--mono); font-size: 10px; letter-spacing: 0.12em;
        text-transform: uppercase; color: var(--faint);
      }
      .kpi .k-value { font-family: var(--mono); font-size: 25px; font-weight: 500; margin-top: 6px; letter-spacing: -0.01em; }
      .kpi .k-foot { font-size: 11.5px; color: var(--muted); margin-top: 4px; }
      .k-teal { color: var(--teal); } .k-amber { color: var(--amber); }
      .k-rose { color: var(--rose); } .k-violet { color: var(--violet); }

      .empty {
        border: 1px dashed var(--line); border-radius: var(--radius);
        padding: 30px 26px; color: var(--muted); font-size: 13px; line-height: 1.6;
        background: rgba(18,24,36,0.45);
      }
      .empty strong { color: var(--text); font-weight: 600; display: block; margin-bottom: 6px; }
      .empty code {
        font-family: var(--mono); font-size: 12px; color: var(--teal);
        background: rgba(47,191,160,0.09); padding: 2px 6px; border-radius: 5px;
      }

      .readout { font-family: var(--mono); font-size: 12px; color: var(--muted); line-height: 1.9; }
      .readout b { color: var(--text); font-weight: 500; }
      .bar-row { display: grid; grid-template-columns: minmax(0, 1.1fr) 1.5fr 54px; gap: 10px; align-items: center; margin-bottom: 5px; }
      .bar-row .name { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .bar-row .track { height: 7px; background: rgba(255,255,255,0.05); border-radius: 4px; overflow: hidden; }
      .bar-row .fill { height: 100%; border-radius: 4px; }
      .bar-row .val { font-family: var(--mono); font-size: 11.5px; color: var(--text); text-align: right; }

      /* ---- controls ------------------------------------------------ */
      button.action {
        border: 1px solid var(--line); background: rgba(24,32,46,0.8); color: var(--text);
        border-radius: 8px; padding: 8px 14px; font-family: var(--ui); font-size: 12.5px; cursor: pointer;
      }
      button.action:hover { border-color: var(--teal); color: var(--teal); }
      button:focus-visible, .chip:focus-visible, .nav-item:focus-visible {
        outline: 2px solid var(--blue); outline-offset: 2px;
      }
      .Select-control, .Select-menu-outer, .Select--multi .Select-value {
        background: rgba(16,22,33,0.9) !important; border-color: var(--line) !important;
        color: var(--text) !important; font-size: 12.5px;
      }
      .Select-value-label, .Select-placeholder, .Select--single > .Select-control .Select-value {
        color: var(--muted) !important;
      }
      .Select--multi .Select-value { color: var(--teal) !important; border-color: rgba(47,191,160,0.35) !important; }
      .Select-menu-outer { border-color: var(--line) !important; }
      .VirtualizedSelectOption { background: var(--surface) !important; color: var(--muted) !important; }
      .VirtualizedSelectFocusedOption { background: rgba(47,191,160,0.14) !important; color: var(--text) !important; }
      .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td,
      .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
        background: transparent !important; border-color: var(--line) !important; color: var(--text) !important;
      }
      @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
    </style>
</head>
<body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""


def index_html() -> str:
    replacements = {
        "__INK__": INK,
        "__SURFACE__": SURFACE,
        "__RAISED__": SURFACE_RAISED,
        "__LINE__": LINE,
        "__TEXT__": TEXT,
        "__MUTED__": MUTED,
        "__FAINT__": FAINT,
        "__TEAL__": TEAL,
        "__AMBER__": AMBER,
        "__ROSE__": ROSE,
        "__VIOLET__": VIOLET,
        "__BLUE__": BLUE,
        "__FONT_UI__": FONT_UI,
        "__FONT_MONO__": FONT_MONO,
    }
    html = INDEX_HTML
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html
