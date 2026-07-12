# -*- coding: utf-8 -*-
"""
ADN DE RIESGOS · Matriz DAFO de Riesgos
Herramienta de análisis para planificación urbanística.

Ejecución:
    pip install streamlit pandas plotly matplotlib openpyxl
    streamlit run app_dafo_riesgos.py

Tema (recomendado): crea un fichero .streamlit/config.toml junto a este script
para fijar el modo oscuro con independencia del sistema operativo:

    [theme]
    base = "dark"
    primaryColor = "#c2544c"
    backgroundColor = "#111317"
    secondaryBackgroundColor = "#1b1e24"
    textColor = "#e6e2da"

Pantalla  → gráfico interactivo Plotly oscuro (tooltips, zoom, comparación).
Documento → exportación vectorial matplotlib (PDF / SVG / PNG 300 dpi),
            con fondo claro (imprenta) u oscuro (pantalla/proyección).
"""

import io
import re
import unicodedata

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ════════════════════════════════════════════════════════════════
# 1 · CONSTANTES DE CÁLCULO
# ════════════════════════════════════════════════════════════════

PROB_SCALE = {"MUY BAJA": 0.1, "BAJA": 0.3, "MEDIA": 0.5, "ALTA": 0.7, "MUY ALTA": 0.9}
IMP_SCALE = {"MUY BAJO": 0.05, "BAJO": 0.1, "MEDIO": 0.2, "ALTO": 0.4, "MUY ALTO": 0.8}
PROB_LABELS = list(PROB_SCALE)
IMP_LABELS = list(IMP_SCALE)
PROB_NAME = {v: k for k, v in PROB_SCALE.items()}

# Matriz de riesgo cualitativa (ASIMÉTRICA: penaliza amenazas frente a oportunidades)
# Clave: (probabilidad, impacto con signo)
_M = {
    0.9: {-0.05: "MODERADO", -0.1: "MODERADO", -0.2: "ALTO", -0.4: "ALTO", -0.8: "ALTO",
          0.8: "ALTO", 0.4: "ALTO", 0.2: "ALTO", 0.1: "MODERADO", 0.05: "BAJO"},
    0.7: {-0.05: "BAJO", -0.1: "MODERADO", -0.2: "MODERADO", -0.4: "ALTO", -0.8: "ALTO",
          0.8: "ALTO", 0.4: "ALTO", 0.2: "MODERADO", 0.1: "MODERADO", 0.05: "BAJO"},
    0.5: {-0.05: "BAJO", -0.1: "MODERADO", -0.2: "MODERADO", -0.4: "ALTO", -0.8: "ALTO",
          0.8: "ALTO", 0.4: "ALTO", 0.2: "MODERADO", 0.1: "BAJO", 0.05: "BAJO"},
    0.3: {-0.05: "BAJO", -0.1: "BAJO", -0.2: "MODERADO", -0.4: "MODERADO", -0.8: "ALTO",
          0.8: "ALTO", 0.4: "MODERADO", 0.2: "MODERADO", 0.1: "BAJO", 0.05: "BAJO"},
    0.1: {-0.05: "BAJO", -0.1: "BAJO", -0.2: "BAJO", -0.4: "BAJO", -0.8: "MODERADO",
          0.8: "MODERADO", 0.4: "BAJO", 0.2: "BAJO", 0.1: "BAJO", 0.05: "BAJO"},
}
RISK_MATRIX = {(round(p, 2), round(i, 2)): n for p, cols in _M.items() for i, n in cols.items()}

RISK_COLORS = {"BAJO": "#6f9e47", "MODERADO": "#f0a72e", "ALTO": "#d0603f"}
GARNET = "#7a1518"          # granate institucional (documentos, fondo claro)
ACCENT = "#c2544c"          # granate claro (interfaz y fondo oscuro)

# Paleta de la interfaz (modo oscuro)
DK = {"bg": "#111317", "card": "#1b1e24", "border": "#2c3039",
      "text": "#e6e2da", "muted": "#8f8c96", "grid": "#2e323b", "grid2": "#262a32"}

PERIOD_STROKES = ["#e0736a", "#5b8dd6", "#7fb069", "#d9a441", "#a07bd8", "#4fb3b3"]
PERIOD_STROKES_LIGHT = ["#7a1518", "#1f4e8c", "#3d6b21", "#8a5b00", "#5b2d8a", "#0f6b6b"]

INPUT_COLS = ["CODIGO", "RIESGO", "DATO", "COMENTARIO",
              "SIST/ESPEC", "TIPO", "PROBABILIDAD", "IMPACTO", "PERIODO", "X"]

# ════════════════════════════════════════════════════════════════
# 2 · PIPELINE DE CÁLCULO  (clasificación → cuantificación → matriz)
# ════════════════════════════════════════════════════════════════

def _strip(s) -> str:
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()


def parse_prob(v):
    s = _strip(v)
    if "MUY" in s and ("ALTA" in s or "ALTO" in s):
        return "MUY ALTA"
    if "MUY" in s and ("BAJA" in s or "BAJO" in s):
        return "MUY BAJA"
    if "ALTA" in s or s == "ALTO":
        return "ALTA"
    if "BAJA" in s or s == "BAJO":
        return "BAJA"
    if "MEDIA" in s or s == "MEDIO":
        return "MEDIA"
    return None


def parse_imp(v):
    s = _strip(v)
    if "MUY" in s and ("ALTO" in s or "ALTA" in s):
        return "MUY ALTO"
    if "MUY" in s and ("BAJO" in s or "BAJA" in s):
        return "MUY BAJO"
    if "ALTO" in s or s == "ALTA":
        return "ALTO"
    if "BAJO" in s or s == "BAJA":
        return "BAJO"
    if "MEDIO" in s or s == "MEDIA":
        return "MEDIO"
    return None


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva todas las columnas calculadas a partir de las de entrada."""
    if df.empty:
        return df.assign(**{c: [] for c in
                            ["DAFO", "PROB_V", "IMP_MAG", "IMP_SIGNO", "VALOR", "Y_GRAF", "NIVEL", "COLOR"]})
    out = df.copy()
    out["PROBABILIDAD"] = out["PROBABILIDAD"].map(parse_prob)
    out["IMPACTO"] = out["IMPACTO"].map(parse_imp)
    out["PROB_V"] = out["PROBABILIDAD"].map(PROB_SCALE)
    out["IMP_MAG"] = out["IMPACTO"].map(IMP_SCALE)
    neg = out["TIPO"].eq("NEGATIVO")
    out["IMP_SIGNO"] = out["IMP_MAG"].where(~neg, -out["IMP_MAG"])
    out["VALOR"] = (out["PROB_V"] * out["IMP_SIGNO"]).round(4)
    sist = out["SIST/ESPEC"].eq("SISTEMATICO")
    out["DAFO"] = ["AMENAZA" if n and s else "DEBILIDAD" if n else
                   "OPORTUNIDAD" if s else "FORTALEZA"
                   for n, s in zip(neg, sist)]
    # Convención: impacto NEGATIVO → zona superior (Y+); POSITIVO → zona inferior (Y−)
    out["Y_GRAF"] = out["PROB_V"].where(neg, -out["PROB_V"])
    out["NIVEL"] = [RISK_MATRIX[(round(p, 2), round(i, 2))]
                    for p, i in zip(out["PROB_V"], out["IMP_SIGNO"])]
    out["COLOR"] = out["NIVEL"].map(RISK_COLORS)
    return out


def _natkey(code: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(code))]


def auto_assign_x(df: pd.DataFrame) -> pd.DataFrame:
    """Sistemáticos → índices X negativos; específicos → positivos.
    Un mismo código conserva su X en todos los periodos."""
    if df.empty:
        return df
    first = df.drop_duplicates("CODIGO").set_index("CODIGO")["SIST/ESPEC"]
    neg = pos = 0
    xmap = {}
    for code in sorted(first.index, key=_natkey):
        if first[code] == "SISTEMATICO":
            neg -= 1
            xmap[code] = neg
        else:
            pos += 1
            xmap[code] = pos
    out = df.copy()
    out["X"] = out["CODIGO"].map(xmap)
    return out

# ════════════════════════════════════════════════════════════════
# 3 · IMPORTACIÓN  (esquema limpio o hoja TABLA de los Excel legados)
# ════════════════════════════════════════════════════════════════

HEADER_ALIASES = {
    "CODIGO": "CODIGO", "RIESGO": "RIESGO", "INDICADOR": "RIESGO", "FACTOR": "RIESGO",
    "DATO": "DATO", "COMENTARIO": "COMENTARIO", "PERIODO": "PERIODO", "X": "X",
}


def _map_headers(header_row):
    idx = {}
    for i, h in enumerate(header_row):
        s = _strip(h)
        if s in HEADER_ALIASES:
            idx.setdefault(HEADER_ALIASES[s], i)
        elif "SIST" in s:
            idx.setdefault("SIST/ESPEC", i)
        elif "NEG" in s or s in ("TIPO", "SIGNO"):
            idx.setdefault("TIPO", i)
        elif s.startswith("PROBABILIDAD"):
            idx.setdefault("PROBABILIDAD", i)
        elif s == "IMPACTO":
            idx.setdefault("IMPACTO", i)
    return idx


def rows_from_matrix(matrix, default_period: str) -> pd.DataFrame:
    h_idx = next((i for i, row in enumerate(matrix)
                  if any(_strip(c) == "CODIGO" for c in row)), None)
    if h_idx is None:
        raise ValueError("No se encuentra ninguna fila de cabecera con la columna CODIGO.")
    idx = _map_headers(matrix[h_idx])
    for req in ("CODIGO", "PROBABILIDAD", "IMPACTO"):
        if req not in idx:
            raise ValueError(f"La cabecera debe incluir la columna {req}.")

    def cell(row, key, default=""):
        i = idx.get(key)
        v = row[i] if i is not None and i < len(row) else default
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()

    rows = []
    for row in matrix[h_idx + 1:]:
        codigo = cell(row, "CODIGO")
        prob, imp = parse_prob(cell(row, "PROBABILIDAD")), parse_imp(cell(row, "IMPACTO"))
        if not codigo or not prob or not imp:
            continue
        try:
            x = float(cell(row, "X"))
        except ValueError:
            x = None
        rows.append({
            "CODIGO": codigo,
            "RIESGO": cell(row, "RIESGO"),
            "DATO": cell(row, "DATO"),
            "COMENTARIO": cell(row, "COMENTARIO"),
            "SIST/ESPEC": "SISTEMATICO" if _strip(cell(row, "SIST/ESPEC")).startswith("SIST") else "ESPECIFICO",
            "TIPO": "POSITIVO" if _strip(cell(row, "TIPO")).startswith("POS") else "NEGATIVO",
            "PROBABILIDAD": prob,
            "IMPACTO": imp,
            "PERIODO": cell(row, "PERIODO") or default_period,
            "X": x,
        })
    if not rows:
        raise ValueError("No se ha leído ninguna fila válida (revisa PROBABILIDAD e IMPACTO).")
    return pd.DataFrame(rows, columns=INPUT_COLS)


def read_uploaded(file, default_period: str) -> pd.DataFrame:
    if file.name.lower().endswith(".csv"):
        # sep=None + engine python: detecta automáticamente ";" (Excel español) o ","
        raw = pd.read_csv(file, header=None, dtype=str, keep_default_na=False,
                          sep=None, engine="python", encoding="utf-8-sig")
        matrix = raw.values.tolist()
    else:
        xls = pd.ExcelFile(file)
        sheet = next((s for s in xls.sheet_names if _strip(s) == "TABLA"), xls.sheet_names[0])
        raw = xls.parse(sheet, header=None, dtype=object)
        matrix = raw.values.tolist()
    return rows_from_matrix(matrix, default_period)

# ════════════════════════════════════════════════════════════════
# 4 · DATOS DE DEMOSTRACIÓN
# ════════════════════════════════════════════════════════════════

def demo_data() -> pd.DataFrame:
    base = [
        ("R01", "Tasa de crecimiento del municipio", "TC = −15,1%", "Envejecimiento de la población", "SISTEMATICO", "NEGATIVO", "MEDIA", "ALTO"),
        ("R02", "Envejecimiento en núcleos secundarios", ">65 años = 41,2%", "Despoblación del núcleo", "SISTEMATICO", "NEGATIVO", "MUY ALTA", "MUY ALTO"),
        ("R03", "Hogares con todos los miembros en paro", "45,4%", "Vulnerabilidad económica", "SISTEMATICO", "NEGATIVO", "ALTA", "MEDIO"),
        ("R04", "Fondos europeos de regeneración", "Convocatoria abierta", "Financiación externa disponible", "SISTEMATICO", "POSITIVO", "MEDIA", "ALTO"),
        ("D01", "Calidad edificatoria del caserío", "Índice 0,53", "Necesidad moderada de rehabilitación", "ESPECIFICO", "NEGATIVO", "ALTA", "MEDIO"),
        ("D02", "Contaminación visual en ejes comerciales", "—", "Rotulación no regulada", "ESPECIFICO", "NEGATIVO", "MUY ALTA", "MUY BAJO"),
        ("D03", "Infravivienda en el borde histórico", "112 unidades", "Concentración en 3 manzanas", "ESPECIFICO", "NEGATIVO", "MEDIA", "MUY ALTO"),
        ("F01", "Patrimonio monumental catalogado", "48 BIC", "Alto potencial de atracción", "ESPECIFICO", "POSITIVO", "MUY ALTA", "ALTO"),
        ("F02", "Tejido asociativo vecinal activo", "23 asociaciones", "Capacidad de participación", "ESPECIFICO", "POSITIVO", "ALTA", "MEDIO"),
        ("O01", "Demanda creciente de turismo cultural", "+12% anual", "Tendencia regional sostenida", "SISTEMATICO", "POSITIVO", "ALTA", "ALTO"),
    ]
    evol = {"R01": ("ALTA", "ALTO"), "R02": ("MUY ALTA", "ALTO"), "D01": ("MEDIA", "MEDIO"),
            "D03": ("BAJA", "MUY ALTO"), "F01": ("MUY ALTA", "MUY ALTO"), "O01": ("MUY ALTA", "ALTO")}
    rows = []
    for cod, rsg, dato, com, se, tp, pr, im in base:
        rows.append(dict(CODIGO=cod, RIESGO=rsg, DATO=dato, COMENTARIO=com,
                         **{"SIST/ESPEC": se}, TIPO=tp, PROBABILIDAD=pr, IMPACTO=im,
                         PERIODO="Año 1", X=None))
        p2, i2 = evol.get(cod, (pr, im))
        rows.append(dict(CODIGO=cod, RIESGO=rsg, DATO=dato, COMENTARIO=com,
                         **{"SIST/ESPEC": se}, TIPO=tp, PROBABILIDAD=p2, IMPACTO=i2,
                         PERIODO="Año 2", X=None))
    return auto_assign_x(pd.DataFrame(rows, columns=INPUT_COLS))

# ════════════════════════════════════════════════════════════════
# 5 · GRÁFICO INTERACTIVO (Plotly · pantalla)
# ════════════════════════════════════════════════════════════════

def period_style(period, visible_periods, dark=True):
    i = max(0, visible_periods.index(period)) if period in visible_periods else 0
    last = i == len(visible_periods) - 1
    palette = PERIOD_STROKES if dark else PERIOD_STROKES_LIGHT
    return {"stroke": palette[i % len(palette)],
            "opacity": 0.68 if last else 0.32}


def _x_range(df):
    xs = df["X"].fillna(0)
    lo = min(-2, xs.min() if len(xs) else -2) - 1.6
    hi = max(2, xs.max() if len(xs) else 2) + 1.6
    return lo, hi


def plotly_chart(df: pd.DataFrame, comparison: bool, visible_periods: list) -> go.Figure:
    fig = go.Figure()
    lo, hi = _x_range(df)

    # Trayectorias entre periodos (comparación)
    if comparison and len(visible_periods) > 1:
        order = {p: i for i, p in enumerate(visible_periods)}
        for _, g in df.groupby("CODIGO"):
            g = g.sort_values("PERIODO", key=lambda s: s.map(order))
            if len(g) < 2:
                continue
            pts = g[["X", "Y_GRAF"]].values
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                fig.add_annotation(x=x2, y=y2, ax=x1, ay=y1,
                                   xref="x", yref="y", axref="x", ayref="y",
                                   showarrow=True, arrowhead=3, arrowsize=1.1,
                                   arrowwidth=1.5, arrowcolor="#b8b4ac", opacity=0.85)

    # Burbujas, un trazo por periodo (las grandes al fondo)
    for period in visible_periods:
        sub = df[df["PERIODO"] == period].sort_values("IMP_MAG", ascending=False)
        if sub.empty:
            continue
        ps = period_style(period, visible_periods, dark=True)
        custom = sub[["CODIGO", "RIESGO", "DATO", "COMENTARIO", "DAFO", "PERIODO",
                      "PROBABILIDAD", "PROB_V", "IMPACTO", "IMP_SIGNO", "VALOR", "NIVEL"]].values
        fig.add_trace(go.Scatter(
            x=sub["X"], y=sub["Y_GRAF"], mode="markers+text",
            text=sub["CODIGO"], textposition="middle center",
            textfont=dict(size=10.5, color="#f3efe7", family="Segoe UI, sans-serif"),
            marker=dict(
                size=(16 + sub["IMP_MAG"] ** 0.5 * 76),
                sizemode="diameter",
                color=sub["COLOR"], opacity=ps["opacity"],
                line=dict(color=ps["stroke"] if comparison else sub["COLOR"],
                          width=2.2 if comparison else 1.2),
            ),
            name=str(period),
            customdata=custom,
            hovertemplate=(
                "<b>%{customdata[0]} · %{customdata[4]} · %{customdata[5]}</b><br>"
                "%{customdata[1]}<br>"
                "Dato: %{customdata[2]}<br>"
                "Comentario: %{customdata[3]}<br>"
                "Probabilidad: %{customdata[6]} (%{customdata[7]:.1f})<br>"
                "Impacto: %{customdata[8]} (%{customdata[9]:.2f})<br>"
                "Valor de riesgo: <b>%{customdata[10]:.3f}</b><br>"
                "Nivel: <b>%{customdata[11]}</b><extra></extra>"
            ),
        ))

    ticks = [0.9, 0.7, 0.5, 0.3, 0.1]
    fig.update_layout(
        height=640,
        plot_bgcolor=DK["card"], paper_bgcolor=DK["card"],
        font=dict(family="Segoe UI, sans-serif", color=DK["text"]),
        showlegend=comparison,
        legend=dict(orientation="h", y=1.06, x=0, title="Periodo",
                    font=dict(color=DK["text"])),
        margin=dict(l=60, r=95, t=40, b=60),
        hoverlabel=dict(bgcolor="#23262e", bordercolor=ACCENT,
                        font=dict(color=DK["text"], size=12)),
        xaxis=dict(
            title="Eje de indicadores", range=[lo, hi],
            gridcolor=DK["grid2"], griddash="dot", zeroline=False,
            tickfont=dict(size=10, color=DK["muted"]),
            title_font=dict(color=DK["muted"]),
        ),
        yaxis=dict(
            title="Probabilidad de ocurrencia", range=[-1.05, 1.05],
            gridcolor=DK["grid"], griddash="dot", zeroline=False,
            tickvals=[t for t in ticks] + [-t for t in ticks],
            ticktext=[PROB_NAME[t] for t in ticks] * 2,
            tickfont=dict(size=9, color=DK["muted"]),
            title_font=dict(color=DK["muted"]),
        ),
        shapes=[  # ejes principales en granate claro
            dict(type="line", x0=lo, x1=hi, y0=0, y1=0,
                 line=dict(color=ACCENT, width=2.4)),
            dict(type="line", x0=0, x1=0, y0=-1.05, y1=1.05,
                 line=dict(color=ACCENT, width=2.4)),
        ],
        annotations=list(fig.layout.annotations) + [
            dict(x=1.005, y=0.55, xref="paper", yref="y", text="<b>NEGATIVO</b>",
                 showarrow=False, font=dict(size=11, color=ACCENT), xanchor="left"),
            dict(x=1.005, y=-0.55, xref="paper", yref="y", text="<b>POSITIVO</b>",
                 showarrow=False, font=dict(size=11, color=ACCENT), xanchor="left"),
        ],
    )
    return fig

# ════════════════════════════════════════════════════════════════
# 6 · FIGURA EDITORIAL (matplotlib · documento)
# ════════════════════════════════════════════════════════════════

def matplotlib_figure(df: pd.DataFrame, comparison: bool, visible_periods: list,
                      title: str = "", dark: bool = False) -> plt.Figure:
    # Paleta editorial según fondo
    if dark:
        c_bg, c_axis, c_grid, c_grid2 = DK["card"], ACCENT, "#3a3e48", "#2c3038"
        c_lbl, c_muted, c_code = DK["text"], DK["muted"], "#f3efe7"
    else:
        c_bg, c_axis, c_grid, c_grid2 = "white", GARNET, "#c9c9c9", "#e3e0da"
        c_lbl, c_muted, c_code = "#555555", "#999999", "#40200f"

    fig, ax = plt.subplots(figsize=(12.5, 7.2), dpi=100)
    fig.patch.set_facecolor(c_bg)
    ax.set_facecolor(c_bg)
    lo, hi = _x_range(df)

    # Rejilla discontinua fina
    ticks = [0.9, 0.7, 0.5, 0.3, 0.1]
    for t in ticks + [-t for t in ticks]:
        ax.axhline(t, color=c_grid, lw=0.6, ls=(0, (3, 4)), zorder=0)
    for x in range(int(lo), int(hi) + 1):
        if x != 0:
            ax.axvline(x, color=c_grid2, lw=0.6, ls=(0, (3, 4)), zorder=0)

    # Ejes principales en granate
    ax.axhline(0, color=c_axis, lw=2.2, zorder=1)
    ax.axvline(0, color=c_axis, lw=2.2, zorder=1)

    # Trayectorias
    if comparison and len(visible_periods) > 1:
        order = {p: i for i, p in enumerate(visible_periods)}
        for _, g in df.groupby("CODIGO"):
            g = g.sort_values("PERIODO", key=lambda s: s.map(order))
            if len(g) < 2:
                continue
            pts = g[["X", "Y_GRAF"]].values
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1), zorder=2,
                            arrowprops=dict(arrowstyle="-|>",
                                            color="#b8b4ac" if dark else "#444444",
                                            lw=1.2, ls=(0, (5, 3)), shrinkA=4, shrinkB=4))

    # Burbujas (área ∝ impacto)
    for period in visible_periods:
        sub = df[df["PERIODO"] == period].sort_values("IMP_MAG", ascending=False)
        if sub.empty:
            continue
        ps = period_style(period, visible_periods, dark=dark)
        ax.scatter(sub["X"], sub["Y_GRAF"], s=sub["IMP_MAG"] * 5200,
                   c=sub["COLOR"], alpha=ps["opacity"],
                   edgecolors=ps["stroke"] if comparison else sub["COLOR"],
                   linewidths=1.8 if comparison else 0.9, zorder=3)
        for _, r in sub.iterrows():
            ax.annotate(r["CODIGO"], (r["X"], r["Y_GRAF"]),
                        ha="center", va="center", fontsize=7.5,
                        color=c_code, fontweight="bold", zorder=4)

    # Escalas y rótulos
    ax.set_xlim(lo, hi)
    ax.set_ylim(-1.05, 1.05)
    ax.set_yticks(ticks + [-t for t in ticks])
    ax.set_yticklabels([PROB_NAME[t] for t in ticks] * 2, fontsize=7, color=c_muted)
    ax.tick_params(axis="x", labelsize=7, colors=c_muted, length=0)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Eje de indicadores", fontsize=9, color=c_lbl, labelpad=8)
    ax.set_ylabel("Probabilidad de ocurrencia", fontsize=9, color=c_lbl, labelpad=8)
    ax.text(1.005, 0.76, "NEGATIVO", transform=ax.transAxes, fontsize=9,
            color=c_axis, fontweight="bold", va="center")
    ax.text(1.005, 0.24, "POSITIVO", transform=ax.transAxes, fontsize=9,
            color=c_axis, fontweight="bold", va="center")
    if title:
        ax.set_title(title, fontsize=12, color=c_axis, fontweight="bold", pad=14)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Leyenda: nivel de riesgo + impacto (+ periodos si hay comparación)
    handles = [Line2D([], [], marker="o", ls="", markersize=9, alpha=0.75,
                      markerfacecolor=c, markeredgecolor=c, label=f"Riesgo {n.lower()}")
               for n, c in RISK_COLORS.items()]
    handles += [Line2D([], [], marker="o", ls="", markerfacecolor="none",
                       markeredgecolor=c_muted,
                       markersize=(IMP_SCALE[l] * 5200) ** 0.5 * 0.55,
                       label=f"Impacto {l.lower()}")
                for l in IMP_LABELS]
    if comparison:
        handles += [Line2D([], [], marker="o", ls="", markerfacecolor="none", markersize=9,
                           markeredgewidth=1.8,
                           markeredgecolor=period_style(p, visible_periods, dark=dark)["stroke"],
                           label=str(p))
                    for p in visible_periods]
    leg = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.10),
                    ncol=len(handles) if len(handles) <= 8 else 6,
                    frameon=False, fontsize=7.5, handletextpad=0.4, columnspacing=1.1,
                    labelcolor=c_lbl)
    fig.tight_layout()
    return fig


def figure_bytes(fig: plt.Figure, fmt: str) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=300 if fmt == "png" else "figure",
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()

# ════════════════════════════════════════════════════════════════
# 7 · INTERFAZ STREAMLIT
# ════════════════════════════════════════════════════════════════

st.set_page_config(page_title="ADN de Riesgos · Matriz DAFO", layout="wide", page_icon="◉")

st.markdown(f"""
<style>
    .stApp {{ background: {DK["bg"]}; }}
    h1 {{ color: {ACCENT} !important; letter-spacing: 0.02em; }}
    h2, h3 {{ color: {DK["text"]} !important;
              border-bottom: 2px solid {ACCENT}; padding-bottom: 4px; }}
    [data-testid="stSidebar"] {{ background: {DK["card"]};
              border-right: 1px solid {DK["border"]}; }}
    div[data-testid="stMetric"] {{
        background: {DK["card"]}; border: 1px solid {DK["border"]};
        border-left: 4px solid {ACCENT};
        border-radius: 6px; padding: 10px 14px;
    }}
    div[data-testid="stMetric"] label {{ color: {DK["muted"]} !important; }}
    div[data-testid="stMetricValue"] {{ color: {DK["text"]} !important; }}
    .stCaption, small {{ color: {DK["muted"]}; }}
</style>
""", unsafe_allow_html=True)

if "rows" not in st.session_state:
    st.session_state.rows = demo_data()

# ---------- Barra lateral: datos ----------
with st.sidebar:
    st.header("Datos")
    default_period = st.text_input("Periodo si el fichero no lo indica", "Año 1")
    up = st.file_uploader("Importar Excel / CSV", type=["xlsx", "xls", "csv"],
                          help="Acepta el esquema limpio de 9 columnas o los Excel legados con hoja TABLA.")
    if up is not None and st.session_state.get("_last_file") != up.name + str(up.size):
        try:
            imported = read_uploaded(up, default_period.strip() or "Año 1")
            merged = pd.concat([st.session_state.rows, imported], ignore_index=True)
            if merged["X"].isna().any():
                merged = auto_assign_x(merged)
            st.session_state.rows = merged
            st.session_state["_last_file"] = up.name + str(up.size)
            st.success(f"Importados {len(imported)} indicadores de {up.name}.")
        except Exception as e:
            st.error(f"Error al importar: {e}")

    c1, c2 = st.columns(2)
    if c1.button("Reasignar eje X", use_container_width=True):
        st.session_state.rows = auto_assign_x(st.session_state.rows)
    if c2.button("Vaciar datos", use_container_width=True):
        st.session_state.rows = pd.DataFrame(columns=INPUT_COLS)

    st.caption("Matriz de riesgo asimétrica: penaliza las amenazas frente a las "
               "oportunidades. Zona superior = impacto negativo; inferior = positivo.")

rows = st.session_state.rows
computed = compute(rows)
periods = list(dict.fromkeys(rows["PERIODO"])) if not rows.empty else []

# ---------- Cabecera y controles de periodo ----------
st.title("ADN de Riesgos · Matriz DAFO")
st.caption("Evaluación cualitativa de factores estratégicos · Planificación urbanística")

cc1, cc2, cc3 = st.columns([1.2, 1, 2.2])
comparison = cc1.toggle("Modo comparación", value=False,
                        help="Superpone periodos y traza la trayectoria de cada indicador.")
if comparison:
    visible_periods = cc3.multiselect("Periodos comparados", periods,
                                      default=periods[:2] if len(periods) >= 2 else periods)
    visible_periods = [p for p in periods if p in visible_periods]  # orden estable
else:
    sel = cc2.selectbox("Periodo mostrado", periods) if periods else None
    visible_periods = [sel] if sel else []

visible = computed[computed["PERIODO"].isin(visible_periods)] if visible_periods else computed.iloc[0:0]

# ---------- Índice agregado ----------
st.subheader("Índice de riesgo agregado del ámbito")
if not visible_periods:
    st.info("Añade o importa indicadores para calcular el índice.")
for p in visible_periods:
    sub = computed[computed["PERIODO"] == p]
    neg, pos = sub.loc[sub["VALOR"] < 0, "VALOR"], sub.loc[sub["VALOR"] > 0, "VALOR"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"{p} · Media riesgos negativos", f"{(neg.mean() if len(neg) else 0):.3f}")
    m2.metric(f"{p} · Media riesgos positivos", f"{(pos.mean() if len(pos) else 0):.3f}")
    m3.metric(f"{p} · Índice global p[risk]", f"{(sub['VALOR'].mean() if len(sub) else 0):.3f}")
    m4.metric(f"{p} · Indicadores en riesgo alto", f"{int((sub['NIVEL'] == 'ALTO').sum())} / {len(sub)}")

# ---------- Gráfico interactivo ----------
st.subheader("Matriz gráfica" + (f" · {' → '.join(map(str, visible_periods))}" if visible_periods else ""))
if not visible.empty:
    st.plotly_chart(plotly_chart(visible, comparison, visible_periods),
                    use_container_width=True, config={"displaylogo": False})
else:
    st.info("Sin indicadores en el periodo seleccionado.")

# ---------- Exportación para documento ----------
st.subheader("Exportar para documento (calidad editorial)")
e1, e2, e3, e4 = st.columns([1, 1, 1.6, 1.4])
fmt = e1.selectbox("Formato", ["pdf", "svg", "png"], format_func=lambda f:
                   {"pdf": "PDF vectorial", "svg": "SVG vectorial", "png": "PNG 300 dpi"}[f])
fondo = e2.selectbox("Fondo", ["claro", "oscuro"], format_func=lambda v:
                     "Claro (imprenta)" if v == "claro" else "Oscuro (pantalla)")
doc_title = e3.text_input("Título de la figura (opcional)", "")
if not visible.empty:
    data = figure_bytes(matplotlib_figure(visible, comparison, visible_periods,
                                          doc_title, dark=(fondo == "oscuro")), fmt)
    e4.write("")  # alinear el botón con los campos
    e4.write("")
    e4.download_button(f"⬇ Descargar .{fmt}", data,
                       file_name=f"matriz_dafo_riesgos.{fmt}",
                       mime={"pdf": "application/pdf", "svg": "image/svg+xml", "png": "image/png"}[fmt],
                       use_container_width=True)

# ---------- Añadir indicador ----------
with st.expander("➕ Añadir indicador", expanded=False):
    f1, f2, f3 = st.columns([1, 2, 1])
    codigo = f1.text_input("Código *", placeholder="R01.3")
    riesgo = f2.text_input("Riesgo / factor", placeholder="Descripción del factor")
    dato = f3.text_input("Dato", placeholder=">65 años = 41,23%")
    comentario = st.text_input("Comentario")
    g1, g2, g3, g4, g5, g6 = st.columns(6)
    sist = g1.selectbox("Naturaleza", ["SISTEMATICO", "ESPECIFICO"],
                        format_func=lambda v: v.capitalize())
    tipo = g2.selectbox("Signo del factor", ["NEGATIVO", "POSITIVO"],
                        format_func=lambda v: "Negativo (perjudicial)" if v == "NEGATIVO" else "Positivo (beneficioso)")
    prob = g3.selectbox("Probabilidad", PROB_LABELS, index=2)
    imp = g4.selectbox("Impacto", IMP_LABELS, index=2)
    periodo = g5.text_input("Periodo *", periods[0] if periods else "Año 1")
    x_manual = g6.text_input("X (vacío = automático)", "")

    prev = compute(pd.DataFrame([{"CODIGO": "·", "RIESGO": "", "DATO": "", "COMENTARIO": "",
                                  "SIST/ESPEC": sist, "TIPO": tipo, "PROBABILIDAD": prob,
                                  "IMPACTO": imp, "PERIODO": "·", "X": 0}])).iloc[0]
    st.caption(f"Vista previa → DAFO: **{prev['DAFO']}** · valor de riesgo: **{prev['VALOR']:.3f}** "
               f"· nivel: **{prev['NIVEL']}**")

    if st.button("Añadir indicador", type="primary"):
        if not codigo.strip() or not periodo.strip():
            st.error("El código y el periodo son obligatorios.")
        else:
            try:
                x_val = float(x_manual) if x_manual.strip() else None
            except ValueError:
                x_val = None
            new = pd.DataFrame([{"CODIGO": codigo.strip(), "RIESGO": riesgo.strip(),
                                 "DATO": dato.strip(), "COMENTARIO": comentario.strip(),
                                 "SIST/ESPEC": sist, "TIPO": tipo, "PROBABILIDAD": prob,
                                 "IMPACTO": imp, "PERIODO": periodo.strip(), "X": x_val}])
            merged = pd.concat([st.session_state.rows, new], ignore_index=True)
            if merged["X"].isna().any():
                merged = auto_assign_x(merged)
            st.session_state.rows = merged
            st.rerun()

# ---------- Tabla editable + tabla calculada ----------
st.subheader(f"Tabla de indicadores ({len(rows)})")
st.caption("Edita cualquier celda; añade filas con «+» o elimínalas seleccionándolas y pulsando Supr. "
           "Los cálculos se actualizan al instante.")

edited = st.data_editor(
    rows, num_rows="dynamic", use_container_width=True, hide_index=True,
    column_config={
        "CODIGO": st.column_config.TextColumn("Código", required=True),
        "RIESGO": st.column_config.TextColumn("Riesgo / factor", width="large"),
        "DATO": st.column_config.TextColumn("Dato"),
        "COMENTARIO": st.column_config.TextColumn("Comentario", width="large"),
        "SIST/ESPEC": st.column_config.SelectboxColumn("Naturaleza", options=["SISTEMATICO", "ESPECIFICO"], required=True),
        "TIPO": st.column_config.SelectboxColumn("Signo", options=["NEGATIVO", "POSITIVO"], required=True),
        "PROBABILIDAD": st.column_config.SelectboxColumn("Probabilidad", options=PROB_LABELS, required=True),
        "IMPACTO": st.column_config.SelectboxColumn("Impacto", options=IMP_LABELS, required=True),
        "PERIODO": st.column_config.TextColumn("Periodo", required=True),
        "X": st.column_config.NumberColumn("X", step=1),
    },
    key="editor",
)
if not edited.equals(rows):
    if edited["X"].isna().any():
        edited = auto_assign_x(edited)
    st.session_state.rows = edited.reset_index(drop=True)
    st.rerun()

with st.expander("Tabla calculada (columnas derivadas)", expanded=False):
    if computed.empty:
        st.info("Sin datos.")
    else:
        show = computed[["CODIGO", "DAFO", "PERIODO", "X", "PROBABILIDAD", "PROB_V",
                         "IMPACTO", "IMP_SIGNO", "VALOR", "NIVEL"]]
        st.dataframe(
            show.style.map(lambda v: f"background-color:{RISK_COLORS.get(v, '')};color:white;font-weight:bold"
                           if v in RISK_COLORS else "", subset=["NIVEL"]),
            use_container_width=True, hide_index=True,
        )
        csv = computed[INPUT_COLS + ["DAFO", "PROB_V", "IMP_SIGNO", "VALOR", "NIVEL"]].to_csv(
            sep=";", decimal=",", index=False).encode("utf-8-sig")
        st.download_button("⬇ Exportar tabla CSV", csv,
                           file_name="tabla_dafo_riesgos.csv", mime="text/csv")
