"""Run inside Origin 2021–2026b embedded Python via ``run -pyf``."""

import csv
import json
import os
import traceback
from collections import defaultdict
from pathlib import Path

import originpro as op


def runtime_value(environment_name, labtalk_name, required=True):
    value = ""
    getter = getattr(op, "get_lt_str", None)
    if getter is not None:
        value = getter(labtalk_name) or ""
    if not value:
        value = os.environ.get(environment_name, "")
    if required and not value:
        raise RuntimeError("Missing Origin runtime value: {}".format(environment_name))
    return value


job_path = Path(runtime_value("ELECTROCHEM_ORIGIN_JOB", "ec_job$"))
job = json.loads(job_path.read_text(encoding="utf-8"))
status_path = Path(job["status_path"])
origin_release = runtime_value(
    "ELECTROCHEM_ORIGIN_RELEASE", "ec_release$", required=False
) or "unknown"
originpro_version = str(getattr(op, "__version__", "unknown"))
compatibility_warnings = []


def set_plot_property_compat(plot, property_name, value, value_type="float"):
    """Set a plot property with fallbacks used by older originpro releases."""
    preferred = "set_float" if value_type == "float" else "set_int"
    fallback = "set_int" if value_type == "float" else "set_float"
    for method_name in (preferred, fallback):
        method = getattr(plot, method_name, None)
        if method is None:
            continue
        try:
            method(property_name, value)
            return True
        except (AttributeError, TypeError, ValueError):
            continue
    compatibility_warnings.append(
        "Could not set {} via originpro {} on Origin {}".format(
            property_name, originpro_version, origin_release
        )
    )
    return False


def set_graph_antialias_compat(graph):
    setter = getattr(graph, "set_int", None)
    if setter is None:
        compatibility_warnings.append("Graph antialias API is unavailable")
        return
    try:
        setter("aa", 1)
    except (AttributeError, TypeError, ValueError):
        compatibility_warnings.append("Graph antialias setting was skipped")


def save_figure_compat(graph, path, width=1800):
    """Use width when accepted; older versions fall back to default export size."""
    try:
        graph.save_fig(path, width=width)
    except TypeError:
        compatibility_warnings.append(
            "save_fig(width=...) is unavailable; exported with the Origin default width"
        )
        graph.save_fig(path)


def style_layer(layer, include_right=False):
    layer.activate()
    commands = [
        "layer.x.thickness=4",
        "layer.y.thickness=4",
        "layer.x.ticks=5",
        "layer.y.ticks=5",
        "layer.x.label.font=font(Times New Roman)",
        "layer.y.label.font=font(Times New Roman)",
        "xb.font=font(Times New Roman)",
        "yl.font=font(Times New Roman)",
        "legend.font=font(Times New Roman)",
        "xb.fsize=22",
        "yl.fsize=22",
        "layer.x.label.fsize=18",
        "layer.y.label.fsize=18",
    ]
    if include_right:
        commands.extend(
            [
                "layer.y2.thickness=4",
                "layer.y2.ticks=5",
                "layer.y2.label.font=font(Times New Roman)",
                "yr.font=font(Times New Roman)",
                "yr.fsize=22",
            ]
        )
    op.lt_exec(";".join(commands) + ";")


def set_plot_style(plot, color, dashed=False):
    try:
        plot.color = color
    except (AttributeError, TypeError, ValueError):
        compatibility_warnings.append("Hex plot color was not accepted: {}".format(color))
    set_plot_property_compat(plot, "line.width", 2.5, "float")
    if dashed:
        set_plot_property_compat(plot, "line.style", 1, "int")


def set_scatter_style(plot, color, symbol_kind, open_symbol=False):
    """Use distinct symbol geometry so capacity series remain legible in grayscale."""
    try:
        plot.color = color
    except (AttributeError, TypeError, ValueError):
        compatibility_warnings.append("Scatter color was not accepted: {}".format(color))
    set_plot_property_compat(plot, "line.connect", 0, "int")
    set_plot_property_compat(plot, "symbol.kind", symbol_kind, "int")
    set_plot_property_compat(plot, "symbol.size", 8, "float")
    set_plot_property_compat(plot, "symbol.edgewidth", 1.4, "float")
    set_plot_property_compat(plot, "symbol.interior", 0 if open_symbol else 1, "int")


def set_efficiency_style(plot, color, symbol_kind=4):
    """Plot independently calculated CE as a thin line with diamond markers."""
    try:
        plot.color = color
    except (AttributeError, TypeError, ValueError):
        compatibility_warnings.append("Efficiency color was not accepted: {}".format(color))
    set_plot_property_compat(plot, "line.width", 1.8, "float")
    set_plot_property_compat(plot, "symbol.kind", symbol_kind, "int")
    set_plot_property_compat(plot, "symbol.size", 7, "float")
    set_plot_property_compat(plot, "symbol.interior", 1, "int")


def set_legend_text_compat(layer, text):
    """Replace auto legends through the documented LabTalk legend.text$ property."""
    custom_text = " " + text
    layer.activate()
    setter = getattr(op, "set_lt_str", None)
    if setter is not None:
        try:
            setter("ec_legend$", custom_text)
            op.lt_exec('legend.text$="";legend.text$=ec_legend$;')
            return
        except (AttributeError, TypeError, ValueError):
            pass
    try:
        legend = layer.label("Legend")
        if legend is None:
            compatibility_warnings.append("Legend object was unavailable; auto legend retained")
            return
        legend.text = ""
        legend.text = custom_text
    except (AttributeError, TypeError, ValueError):
        compatibility_warnings.append("Custom legend text was unavailable; auto legend retained")


def write_status(ok, **extra):
    payload = {
        "ok": ok,
        "project": job.get("project_path"),
        "origin_release": origin_release,
        "originpro_version": originpro_version,
        "compatibility_warnings": compatibility_warnings,
    }
    payload.update(extra)
    status_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


try:
    curves = defaultdict(list)
    with open(job["curves_csv"], "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["cycle"]), row["direction"])
            curves[key].append(
                (float(row["specific_capacity_mAh_g"]), float(row["voltage_V"]))
            )

    curve_sheet = op.new_sheet(type="w", lname="Charge_Discharge_Data")
    curve_graph = op.new_graph(template="line", lname="Charge_Discharge_Curves")
    curve_layer = curve_graph[0]
    colors = [
        "#0072B2", "#D55E00", "#009E73", "#CC79A7",
        "#E69F00", "#56B4E9", "#000000", "#882255",
    ]
    cycle_numbers = sorted({cycle for cycle, _ in curves})
    cycle_colors = {
        cycle: colors[index % len(colors)] for index, cycle in enumerate(cycle_numbers)
    }
    legend_group = []
    axis_pattern = ""
    for index, key in enumerate(sorted(curves)):
        cycle, direction = key
        values = curves[key]
        xcol = index * 2
        ycol = xcol + 1
        label = "Cycle {} {}".format(cycle, direction.capitalize())
        curve_sheet.from_list(
            xcol,
            [item[0] for item in values],
            lname=label + " Capacity",
            units="mAh/g",
        )
        curve_sheet.from_list(
            ycol, [item[1] for item in values], lname=label, units="V"
        )
        axis_pattern += "xy"
        plot = curve_layer.add_plot(
            curve_sheet, coly=ycol, colx=xcol, type="line"
        )
        set_plot_style(plot, cycle_colors[cycle], dashed=(direction == "discharge"))
        if direction == "charge":
            legend_group.append(r"\l({}) Cycle {}".format(index + 1, cycle))
    curve_sheet.cols_axis(axis_pattern)
    curve_layer.axis("x").title = "Specific Capacity (mAh g\\+(−1))"
    curve_layer.axis("y").title = "Voltage (V)"
    curve_layer.rescale()
    set_legend_text_compat(curve_layer, "\n".join(legend_group))
    style_layer(curve_layer)
    set_graph_antialias_compat(curve_graph)

    with open(job["summary_csv"], "r", encoding="utf-8-sig", newline="") as handle:
        summary = [
            row for row in csv.DictReader(handle) if row["complete"].lower() == "true"
        ]
    summary_sheet = op.new_sheet(type="w", lname="Cycle_Summary")
    summary_sheet.from_list(
        0, [float(row["cycle"]) for row in summary], lname="Cycle"
    )
    summary_sheet.from_list(
        1,
        [float(row["charge_specific_capacity_mAh_g"]) for row in summary],
        lname="Charge Capacity",
        units="mAh/g",
    )
    summary_sheet.from_list(
        2,
        [float(row["discharge_specific_capacity_mAh_g"]) for row in summary],
        lname="Discharge Capacity",
        units="mAh/g",
    )
    summary_sheet.from_list(
        3,
        [float(row["coulombic_efficiency_percent"]) for row in summary],
        lname="Coulombic Efficiency",
        units="%",
    )
    summary_sheet.cols_axis("xyyy")

    cycling_graph = op.new_graph(template="DOUBLEY", lname="Cycling_Performance")
    left = cycling_graph[0]
    right = cycling_graph[1]
    p1 = left.add_plot(summary_sheet, coly=1, colx=0, type="scatter")
    p2 = left.add_plot(summary_sheet, coly=2, colx=0, type="scatter")
    p3 = right.add_plot(summary_sheet, coly=3, colx=0, type="line")
    set_scatter_style(p1, "#D55E00", symbol_kind=1, open_symbol=True)
    set_scatter_style(p2, "#0072B2", symbol_kind=3, open_symbol=False)
    set_efficiency_style(p3, "#009E73", symbol_kind=4)
    cycling_legend = "\n".join(
        [
            r"\l(1.1) Charge Capacity",
            r"\l(1.2) Discharge Capacity",
            r"\l(2.1) Coulombic Efficiency",
        ]
    )
    set_legend_text_compat(left, cycling_legend)
    left.axis("x").title = "Cycle Number"
    left.axis("y").title = "Specific Capacity (mAh g\\+(−1))"
    right.axis("y").title = "Coulombic Efficiency (%)"
    left.rescale()
    right.rescale()
    style_layer(left)
    style_layer(right, include_right=True)
    set_graph_antialias_compat(cycling_graph)

    op.save(job["project_path"])
    save_figure_compat(curve_graph, job["curve_png"], width=1800)
    save_figure_compat(cycling_graph, job["cycling_png"], width=1800)
    write_status(True)
except Exception:
    write_status(False, error=traceback.format_exc())
    raise
