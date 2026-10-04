"""Plotly figures for the dashboard (objective 4).

Rules the figures enforce (not just decorate):
  * series that the comparability engine marks `not_comparable` are NEVER drawn
    on the same absolute axis — they go to separate facets, or to the fold-rise
    view, which is the only shared scale;
  * every fitted curve carries its bootstrap band; an unidentifiable fit is
    drawn as points only, with a visible note;
  * values below LLOQ are drawn as open markers, never as if they were measured.

Palette is colour-blind safe (Okabe–Ito) and used consistently: one colour per
compartment, one dash pattern per sampling method.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .comparability import Level, audit_table, compare, context_from_row, series_key
from .kinetics import fit_kinetics, fold_rise_table

COMPARTMENT_COLORS = {
    "nasal": "#0072B2", "oral": "#009E73", "serum": "#D55E00", "blood_cells": "#CC79A7",
}
METHOD_DASH = {
    "nasosorption": "solid", "nasal_wash": "dash", "nasal_swab": "dot",
    "nasopharyngeal_swab": "longdash", "saliva": "dashdot", "serum": "solid", "pbmc": "dot",
}
LEVEL_COLORS = {"comparable": "#009E73", "conditional": "#E69F00", "not_comparable": "#D55E00"}

LAYOUT = dict(
    template="plotly_white", font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=13),
    margin=dict(l=60, r=20, t=60, b=50), legend=dict(orientation="h", y=-0.2),
    hovermode="x unified",
)


def _series_label(row: pd.Series) -> str:
    return (f"{row['compartment']}/{row['method']} · {row['isotype']} · {row['assay']}"
            f" · {row['unit']}" + (f" ({row['normalization']})" if row["normalization"] != "none" else "")
            + f" · {row['lab']}")


def split_comparable_groups(df: pd.DataFrame) -> list[list[str]]:
    """Greedy grouping: series land in the same group only if pairwise comparable
    (or conditional). Each group can safely share one absolute axis."""
    reps = df.assign(_key=df.apply(series_key, axis=1)).drop_duplicates("_key").set_index("_key")
    groups: list[list[str]] = []
    for key in reps.index:
        ctx = context_from_row(reps.loc[key])
        placed = False
        for g in groups:
            if all(compare(ctx, context_from_row(reps.loc[k])).level < Level.not_comparable for k in g):
                g.append(key)
                placed = True
                break
        if not placed:
            groups.append([key])
    return groups


def kinetics_figure(
    df: pd.DataFrame, arm_col: str = "arm_id", n_boot: int = 150, log_y: bool = True,
) -> go.Figure:
    """One facet per comparability group; curves + bootstrap bands."""
    d = df.assign(_key=df.apply(series_key, axis=1))
    groups = split_comparable_groups(df)
    reps = d.drop_duplicates("_key").set_index("_key")
    # Truncating the title at 90 characters silently cut the second series'
    # laboratory off — the one piece of context that explains why two series
    # share a panel. Each series gets its own line instead.
    titles = ["<br>+ ".join(_series_label(reps.loc[k]) for k in g) for g in groups]
    fig = make_subplots(rows=len(groups), cols=1, subplot_titles=titles, vertical_spacing=0.12)
    legend_seen: set[str] = set()

    for r, g in enumerate(groups, start=1):
        for key in g:
            row0 = reps.loc[key]
            color = COMPARTMENT_COLORS.get(row0["compartment"], "#444")
            dash = METHOD_DASH.get(row0["method"], "solid")
            for arm, sub in d[d["_key"] == key].groupby(arm_col):
                fit = fit_kinetics(sub, n_boot=n_boot)
                med = sub.groupby("day")["value"].median().reset_index()
                # The legend identifies the ARM and nothing else. It used to
                # name the arm *and* the series, and to show only the first
                # panel's entries — so a five-panel figure carried two legend
                # keys, both mentioning nasal_wash, while the four other panels
                # went unlabelled. Each panel's title already states its
                # compartment, device, isotype, assay and laboratory; the only
                # thing the reader cannot otherwise tell is which curve is
                # which vaccine. One key per arm, shown once across the figure.
                name = str(arm)
                opacity = 1.0 if "LAIV" in str(arm) or "IN" in str(arm) else 0.65
                first_time = name not in legend_seen
                legend_seen.add(name)
                fig.add_trace(go.Scatter(
                    x=med["day"], y=med["value"], mode="markers", name=name,
                    marker=dict(color=color, size=8, symbol="circle" if opacity == 1 else "square",
                                opacity=opacity),
                    legendgroup=name, showlegend=first_time,
                    hovertemplate="day %{x}<br>median %{y:.3g}<extra>" + name + "</extra>",
                ), row=r, col=1)
                if fit.kinetic.identifiable and np.isfinite(fit.curve_y).any():
                    if fit.band_lo is not None:
                        fig.add_trace(go.Scatter(
                            x=np.concatenate([fit.curve_t, fit.curve_t[::-1]]),
                            y=np.concatenate([fit.band_hi, fit.band_lo[::-1]]),
                            fill="toself", fillcolor=color, opacity=0.13, line=dict(width=0),
                            hoverinfo="skip", showlegend=False, legendgroup=name,
                        ), row=r, col=1)
                    fig.add_trace(go.Scatter(
                        x=fit.curve_t, y=fit.curve_y, mode="lines", line=dict(color=color, dash=dash, width=2),
                        name=name + " (fit)", legendgroup=name, showlegend=False,
                        hovertemplate="fit day %{x:.0f}: %{y:.3g}<extra></extra>",
                    ), row=r, col=1)
                    # A peak the fit places beyond the last visit is an artefact of a
                    # flat or still-rising series, not an observation. Drawing its
                    # marker stretched the x axis to ten times the study (a saliva
                    # series fitted a peak at day 1886 and the panel ran to 1800),
                    # squeezing the real data into the first centimetre. The uncertain
                    # peak is still reported, with its CI, in the parameter table.
                    if np.isfinite(fit.kinetic.peak_day) and fit.kinetic.peak_day <= float(sub["day"].max()):
                        fig.add_vline(x=fit.kinetic.peak_day, line=dict(color=color, width=1, dash="dot"),
                                      row=r, col=1)
                elif len(med):
                    # `row`/`col` already place the annotation in the right subplot;
                    # passing an explicit xref alongside them is rejected by plotly.
                    #
                    # On a log axis plotly reads an annotation's `y` as the EXPONENT,
                    # not the value. Passing a raw 218000 asked for 10^218000, and the
                    # axis obediently grew to 10^112 — flattening every real curve in
                    # that panel to a line at the bottom. It has to be log10 of the
                    # value whenever the axis is logarithmic.
                    #
                    # A panel can hold several series, and an unlabelled note at
                    # the panel's edge looked like a verdict on the whole panel —
                    # including the curves that *were* fitted, right next to it.
                    # It has to name its own series and its own reason, and point
                    # at the last observation it belongs to.
                    y_top = float(med["value"].max())
                    n_days = int(med["day"].nunique())
                    fig.add_annotation(
                        text=(f"{arm} · {row0['method']} ({row0['lab']}): {n_days} timepoints"
                              " — too few to fit, points only"),
                        row=r, col=1,
                        x=float(med["day"].max()),
                        y=(math.log10(y_top) if (log_y and y_top > 0) else y_top),
                        showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor="#D55E00",
                        ax=-40, ay=-26, xanchor="right",
                        font=dict(color="#D55E00", size=10))
        if log_y:
            fig.update_yaxes(type="log", row=r, col=1)
        fig.update_yaxes(title_text="value (own unit)", row=r, col=1)
    fig.update_xaxes(title_text="study day", row=len(groups), col=1)
    # The legend's y offset is a FRACTION of the figure height, so the -0.2 that
    # sits neatly under a single 320px panel becomes a 320px hole under a
    # five-panel, 1600px figure. Converting a fixed 46px gap into the fraction
    # this figure needs keeps the legend just below the axis at any height.
    height = 320 * len(groups)
    layout = {**LAYOUT, "legend": {**LAYOUT["legend"], "y": -46.0 / height}}
    fig.update_layout(height=height, title="Kinetics — one panel per comparable group", **layout)
    return fig


def fold_rise_figure(df: pd.DataFrame, arm_col: str = "arm_id") -> go.Figure:
    """The only legitimate cross-compartment view: fold-rise over own baseline."""
    fr = fold_rise_table(df.assign(_key=df.apply(series_key, axis=1)))
    fig = go.Figure()
    for (comp, method, arm), sub in fr.groupby(["compartment", "method", arm_col]):
        med = sub.groupby("day")["fold_rise"].median().reset_index()
        q1 = sub.groupby("day")["fold_rise"].quantile(0.25).reset_index()["fold_rise"]
        q3 = sub.groupby("day")["fold_rise"].quantile(0.75).reset_index()["fold_rise"]
        color = COMPARTMENT_COLORS.get(comp, "#444")
        name = f"{arm} — {comp}/{method}"
        fig.add_trace(go.Scatter(
            x=np.concatenate([med["day"], med["day"][::-1]]), y=np.concatenate([q3, q1[::-1]]),
            fill="toself", fillcolor=color, opacity=0.12, line=dict(width=0), hoverinfo="skip",
            showlegend=False))
        fig.add_trace(go.Scatter(
            x=med["day"], y=med["fold_rise"], mode="lines+markers", name=name,
            line=dict(color=color, dash=METHOD_DASH.get(method, "solid")),
            hovertemplate="day %{x}<br>fold-rise %{y:.2f}<extra>" + name + "</extra>"))
    fig.add_hline(y=1, line=dict(color="#888", dash="dash"), annotation_text="baseline")
    fig.add_hline(y=4, line=dict(color="#E69F00", dash="dot"),
                  annotation_text="4-fold (conventional threshold — confirm with the expert)")
    fig.update_yaxes(type="log", title_text="fold-rise over own day-0 value")
    fig.update_xaxes(title_text="study day")
    fig.update_layout(title="Mucosal vs systemic — median fold-rise (IQR band)", **LAYOUT)
    return fig


def comparability_heatmap(matrix: pd.DataFrame) -> go.Figure:
    order = ["comparable", "conditional", "not_comparable"]
    z = matrix.replace({k: i for i, k in enumerate(order)}).to_numpy(dtype=float)
    labels = [c[:46] for c in matrix.columns]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels, text=matrix.to_numpy(), texttemplate="%{text}",
        colorscale=[[0, LEVEL_COLORS["comparable"]], [0.5, LEVEL_COLORS["conditional"]],
                    [1, LEVEL_COLORS["not_comparable"]]],
        zmin=0, zmax=2, showscale=False,
        hovertemplate="%{y}<br>vs %{x}<br><b>%{text}</b><extra></extra>"))
    fig.update_layout(title="Pairwise comparability of measurement series",
                      height=140 + 42 * len(labels), **{**LAYOUT, "hovermode": "closest"})
    fig.update_xaxes(tickangle=35)
    return fig


def uncertainty_figure(df: pd.DataFrame) -> go.Figure:
    a = audit_table(df)
    colors = {"low": "#009E73", "medium": "#E69F00", "high": "#D55E00"}
    fig = go.Figure(go.Bar(
        x=a["n_timepoints"], y=[s[:48] for s in a["series"]], orientation="h",
        marker_color=[colors[u] for u in a["uncertainty"]],
        customdata=["; ".join(f) or "no flag" for f in a["flags"]],
        hovertemplate="%{y}<br>timepoints: %{x}<br>%{customdata}<extra></extra>"))
    fig.update_layout(title="Data quality per series (colour = uncertainty level)",
                      xaxis_title="number of distinct timepoints",
                      height=160 + 34 * len(a), **{**LAYOUT, "hovermode": "closest"})
    return fig


def design_figure(candidate_days: list[int], chosen: list[int], mandatory: list[int]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=candidate_days, y=[0] * len(candidate_days), mode="markers",
                             marker=dict(size=9, color="#CCC", symbol="line-ns-open"),
                             name="candidate days"))
    opt = [d for d in chosen if d not in mandatory]
    fig.add_trace(go.Scatter(x=mandatory, y=[0] * len(mandatory), mode="markers+text",
                             marker=dict(size=16, color="#0072B2"), text=["anchor"] * len(mandatory),
                             textposition="top center", name="anchor visits"))
    fig.add_trace(go.Scatter(x=opt, y=[0] * len(opt), mode="markers+text",
                             marker=dict(size=16, color="#009E73", symbol="diamond"),
                             text=["D-opt"] * len(opt), textposition="bottom center",
                             name="added by D-optimal design"))
    fig.update_yaxes(visible=False, range=[-1, 1])
    fig.update_xaxes(title_text="study day")
    fig.update_layout(title="Visit schedule", height=260, **{**LAYOUT, "hovermode": "closest"})
    return fig


def graph_figure(data: dict) -> go.Figure:
    kind_color = {"study": "#0072B2", "finding": "#009E73", "tag": "#E69F00", "method": "#CC79A7",
                  "compartment": "#56B4E9", "platform": "#D55E00", "route": "#999", "assay": "#F0E442"}
    pos = {n["id"]: (n["x"], n["y"]) for n in data["nodes"]}
    ex, ey = [], []
    for e in data["edges"]:
        if e["source"] in pos and e["target"] in pos:
            ex += [pos[e["source"]][0], pos[e["target"]][0], None]
            ey += [pos[e["source"]][1], pos[e["target"]][1], None]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.6, color="#DDD"),
                             hoverinfo="skip", showlegend=False))
    for kind in sorted({n.get("kind", "?") for n in data["nodes"]}):
        ns = [n for n in data["nodes"] if n.get("kind") == kind]
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in ns], y=[n["y"] for n in ns], mode="markers", name=kind,
            marker=dict(size=11 if kind == "study" else 7, color=kind_color.get(kind, "#777")),
            text=[str(n.get("label", n["id"]))[:120] for n in ns],
            hovertemplate="<b>%{text}</b><extra>" + kind + "</extra>"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(title="Evidence knowledge graph", height=620,
                      **{**LAYOUT, "hovermode": "closest"})
    return fig
