"""Literature-aligned electrochemical plot catalog and dependency-free SVG renderer.

The module accepts auditable CSV/TXT exports, normalises units from headers and
writes editable SVG rather than rasterising data.  It does not fit mechanisms:
each plot is a view of supplied or explicitly derived quantities, accompanied
by a JSON record of source hash, detected columns and limitations.
"""

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


NATURE_COLORS = (
    "#E64B35",  # vermilion
    "#4DBBD5",  # cyan
    "#00A087",  # green
    "#3C5488",  # blue
    "#F39B7F",  # salmon
    "#8491B4",  # slate
    "#91D1C2",  # mint
    "#DC0000",  # red
)
FONT_FAMILY = "Arial, 'Microsoft YaHei', sans-serif"
AXIS_STROKE = 1.2
DATA_STROKE = 2.0

TECHNIQUE_REVIEW_DOI = "10.1021/acs.accounts.7b00031"
DIFFERENTIAL_REVIEW_DOI = "10.1021/acs.chemmater.2c01976"
SOLID_ELECTROLYTE_DOI = "10.1039/d0sc06553f"
ARRHENIUS_CAUTION_DOI = "10.1103/physrevresearch.6.023322"


@dataclass(frozen=True)
class PlotSpec:
    plot_type: str
    label: str
    required_columns: Tuple[str, ...]
    scientific_question: str
    limitations: str
    reference_dois: Tuple[str, ...]


PLOT_SPECS: Mapping[str, PlotSpec] = {
    "charge_discharge": PlotSpec(
        "charge_discharge", "充放电曲线", ("specific_capacity_mAh_g", "voltage_V"),
        "容量、电压平台和极化如何随循环变化？",
        "不能仅由曲线确定阻抗、扩散系数或界面反应。",
        (TECHNIQUE_REVIEW_DOI,),
    ),
    "cycling_efficiency": PlotSpec(
        "cycling_efficiency", "循环容量与库仑效率", ("cycle", "discharge_specific_capacity_mAh_g", "coulombic_efficiency_percent"),
        "容量保持和充放电可逆性是否随循环稳定？",
        "单电池曲线不能证明重复性，至少需要三个独立电池。",
        (TECHNIQUE_REVIEW_DOI,),
    ),
    "rate_capability": PlotSpec(
        "rate_capability", "倍率性能", ("cycle", "rate_C", "discharge_specific_capacity_mAh_g"),
        "提高电流负荷后可利用容量能否保持并恢复？",
        "倍率比较必须同时报告载量、面容量、温度和截止条件。",
        (TECHNIQUE_REVIEW_DOI,),
    ),
    "dqdv": PlotSpec(
        "dqdv", "微分容量 dQ/dV", ("voltage_V", "dQ_dV_mAh_g_V"),
        "反应峰位、峰面积和峰形是否随循环发生变化？",
        "数值微分对采样间隔和噪声敏感，不能把峰直接等同于唯一机理。",
        (DIFFERENTIAL_REVIEW_DOI,),
    ),
    "cv_lsv": PlotSpec(
        "cv_lsv", "CV / LSV", ("potential_V", "current_mA"),
        "氧化还原过程、可逆性和电化学稳定边界如何变化？",
        "稳定窗口受电极材料、扫描速率和判据影响，不能只报起始电位。",
        (TECHNIQUE_REVIEW_DOI,),
    ),
    "eis_nyquist": PlotSpec(
        "eis_nyquist", "EIS Nyquist", ("z_real_ohm", "z_imag_ohm"),
        "阻抗谱形状及其随状态变化的趋势是什么？",
        "未通过Kramers–Kronig检查和残差分析时，不宜给出唯一等效电路归属。",
        (TECHNIQUE_REVIEW_DOI, SOLID_ELECTROLYTE_DOI),
    ),
    "eis_bode": PlotSpec(
        "eis_bode", "EIS Bode", ("frequency_Hz", "z_magnitude_ohm", "phase_degree"),
        "不同时间尺度上的阻抗幅值和相位响应是什么？",
        "Bode图用于展示频率响应，参数归属仍需模型、残差和独立证据。",
        (TECHNIQUE_REVIEW_DOI, SOLID_ELECTROLYTE_DOI),
    ),
    "gitt_pitt": PlotSpec(
        "gitt_pitt", "GITT / PITT", ("time_s", "voltage_V"),
        "脉冲极化和弛豫行为如何随状态变化？",
        "扩散系数计算必须核对几何、相变和半无限扩散等假设。",
        (TECHNIQUE_REVIEW_DOI,),
    ),
    "arrhenius": PlotSpec(
        "arrhenius", "电导率 Arrhenius", ("temperature_C", "conductivity_S_cm"),
        "离子电导率的温度依赖和表观活化能如何？",
        "Arrhenius线性并非在所有温区成立，拟合前必须检查分段和相变。",
        (SOLID_ELECTROLYTE_DOI, ARRHENIUS_CAUTION_DOI),
    ),
    "dc_polarization": PlotSpec(
        "dc_polarization", "直流极化", ("time_s", "current_mA"),
        "阻挡电极下的瞬态与稳态电子电流是多少？",
        "电导率换算还需要面积、厚度、电压和稳态判据。",
        (SOLID_ELECTROLYTE_DOI,),
    ),
    "ccd": PlotSpec(
        "ccd", "临界电流密度 CCD", ("time_h", "voltage_V", "current_density_mA_cm2"),
        "对称电池在逐级电流密度下何时出现异常极化或短路？",
        "CCD必须同时报告步长、单步时间、面容量、压力和失效判据。",
        (SOLID_ELECTROLYTE_DOI,),
    ),
}


_FIELD_ALIASES: Sequence[Tuple[str, Tuple[str, ...]]] = (
    ("discharge_specific_capacity_mAh_g", ("dischargespecificcapacity", "dischargecapacity", "放电比容量")),
    ("charge_specific_capacity_mAh_g", ("chargespecificcapacity", "chargecapacity", "充电比容量")),
    ("coulombic_efficiency_percent", ("coulombicefficiency", "库仑效率", "cepercent")),
    ("current_density_mA_cm2", ("currentdensitymacm2", "currentdensity", "电流密度")),
    ("dQ_dV_mAh_g_V", ("dqdv", "dq/dv", "微分容量")),
    ("z_magnitude_ohm", ("zmagnitude", "modulusz", "impedancemagnitude", "阻抗模")),
    ("z_real_ohm", ("zreal", "rez", "zprime", "实部", "z'")),
    ("z_imag_ohm", ("zimag", "imz", "zdoubleprime", "虚部", "z''")),
    ("frequency_Hz", ("frequency", "freq", "频率")),
    ("phase_degree", ("phase", "相位")),
    ("conductivity_S_cm", ("conductivity", "sigma", "电导率")),
    ("temperature_C", ("temperature", "temp", "温度")),
    ("rate_C", ("crate", "ratec", "倍率")),
    ("specific_capacity_mAh_g", ("specificcapacity", "比容量", "capacitymahg")),
    ("potential_V", ("potential", "电位")),
    ("voltage_V", ("voltage", "电压")),
    ("current_mA", ("current", "电流")),
    ("time_s", ("testtime", "totaltime", "elapsedtime", "time", "时间")),
    ("cycle", ("cyclenumber", "cycleno", "cycle", "循环", "圈数")),
    ("scan", ("scannumber", "scan", "扫描圈")),
    ("direction", ("direction", "充放电方向", "方向")),
)


@dataclass(frozen=True)
class PlotTable:
    source: Path
    rows: Tuple[Mapping[str, object], ...]
    detected_columns: Mapping[str, str]
    detected_units: Mapping[str, str]
    delimiter: str
    encoding: str


@dataclass(frozen=True)
class PlotResult:
    plot_type: str
    svg_path: Path
    audit_path: Path
    point_count: int


class PlotDataError(ValueError):
    pass


def _normalise(value: str) -> str:
    text = str(value).strip().casefold().replace("μ", "u").replace("µ", "u").replace("−", "-")
    return "".join(character for character in text if character.isalnum() or character in "'/")


def _canonical_field(header: str) -> Optional[str]:
    normalised = _normalise(header)
    for field, aliases in _FIELD_ALIASES:
        for alias in aliases:
            token = _normalise(alias)
            if token and (normalised == token or token in normalised):
                return field
    return None


def _decode(path: Path) -> Tuple[str, str]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise PlotDataError("文件无法按UTF-8或GB18030解码。")


def _convert(field: str, header: str, value: str) -> object:
    if field == "direction":
        return str(value).strip()
    number = float(str(value).strip())
    if not math.isfinite(number):
        raise ValueError("non-finite value")
    unit = _normalise(header)
    if field == "time_s":
        if "ms" in unit:
            number *= 0.001
        elif "min" in unit or "分钟" in unit:
            number *= 60.0
        elif unit.endswith("h") or "hour" in unit or "小时" in unit or "timeh" in unit:
            number *= 3600.0
    elif field in {"current_mA", "current_density_mA_cm2"}:
        if "ua" in unit:
            number *= 0.001
        elif "ma" not in unit and (unit.endswith("a") or "currenta" in unit):
            number *= 1000.0
    elif field in {"voltage_V", "potential_V"} and "mv" in unit:
        number *= 0.001
    elif field in {"z_real_ohm", "z_imag_ohm", "z_magnitude_ohm"} and "kohm" in unit:
        number *= 1000.0
    elif field == "frequency_Hz" and "khz" in unit:
        number *= 1000.0
    elif field == "temperature_C" and (unit.endswith("k") or "temperaturek" in unit):
        number -= 273.15
    elif field == "conductivity_S_cm" and "mscm" in unit:
        number *= 0.001
    elif "capacity" in field.casefold() and "ahg" in unit and "mahg" not in unit:
        number *= 1000.0
    return number


def load_plot_table(path: Path) -> PlotTable:
    source = Path(path).resolve()
    if source.suffix.casefold() not in {".csv", ".txt", ".tsv", ".dat"}:
        raise PlotDataError("绘图数据必须是CSV、TXT、TSV或DAT文本文件。")
    text, encoding = _decode(source)
    best = None
    for delimiter in (",", "\t", ";"):
        rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        for header_index, headers in enumerate(rows[:50]):
            mapping: Dict[str, int] = {}
            for index, header in enumerate(headers):
                field = _canonical_field(header)
                if field is not None and field not in mapping:
                    mapping[field] = index
            score = len(mapping)
            if score >= 2 and (best is None or score > best[0]):
                best = (score, delimiter, rows, header_index, headers, mapping)
    if best is None:
        raise PlotDataError("未识别到至少两个电化学数据列，请使用图谱窗口给出的标准列名。")
    _, delimiter, raw_rows, header_index, headers, mapping = best
    converted = []
    for source_row, row in enumerate(raw_rows[header_index + 1 :], start=header_index + 2):
        if not row or not any(str(cell).strip() for cell in row):
            continue
        item: Dict[str, object] = {}
        try:
            for field, index in mapping.items():
                if index < len(row) and str(row[index]).strip() != "":
                    item[field] = _convert(field, headers[index], row[index])
        except (TypeError, ValueError) as error:
            raise PlotDataError("第{}行存在无效数值：{}".format(source_row, error)) from error
        if item:
            converted.append(item)
    if len(converted) < 2:
        raise PlotDataError("有效数据少于2行，无法绘图。")
    units = {
        "time_s": "s", "current_mA": "mA", "current_density_mA_cm2": "mA cm-2",
        "voltage_V": "V", "potential_V": "V", "temperature_C": "°C",
        "conductivity_S_cm": "S cm-1", "frequency_Hz": "Hz",
        "z_real_ohm": "ohm", "z_imag_ohm": "ohm", "z_magnitude_ohm": "ohm",
    }
    return PlotTable(
        source=source,
        rows=tuple(converted),
        detected_columns={field: headers[index] for field, index in mapping.items()},
        detected_units={field: units.get(field, "as supplied") for field in mapping},
        delimiter="tab" if delimiter == "\t" else delimiter,
        encoding=encoding,
    )


def _values(rows: Iterable[Mapping[str, object]], x_field: str, y_field: str) -> List[Tuple[float, float]]:
    points = []
    for row in rows:
        if x_field in row and y_field in row:
            x, y = float(row[x_field]), float(row[y_field])
            if math.isfinite(x) and math.isfinite(y):
                points.append((x, y))
    return points


def _group(rows: Sequence[Mapping[str, object]], field: str) -> Mapping[str, List[Mapping[str, object]]]:
    groups: Dict[str, List[Mapping[str, object]]] = {}
    for row in rows:
        label = str(row.get(field, "1"))
        groups.setdefault(label, []).append(row)
    return groups


def _require(table: PlotTable, fields: Sequence[str], plot_type: str) -> None:
    available = set(table.detected_columns)
    missing = [field for field in fields if field not in available]
    if missing:
        raise PlotDataError(
            "{}缺少必要列：{}。已识别：{}".format(
                PLOT_SPECS[plot_type].label, "、".join(missing), "、".join(sorted(available))
            )
        )


def _series_for(plot_type: str, table: PlotTable):
    rows = list(table.rows)
    spec = PLOT_SPECS[plot_type]
    if plot_type == "charge_discharge":
        _require(table, spec.required_columns, plot_type)
        groups: Dict[str, List[Mapping[str, object]]] = {}
        for row in rows:
            label = "Cycle {} {}".format(row.get("cycle", ""), row.get("direction", "")).strip()
            groups.setdefault(label or "Curve", []).append(row)
        return "Specific capacity (mAh g-1)", "Voltage (V)", [
            (label, _values(group, "specific_capacity_mAh_g", "voltage_V"))
            for label, group in groups.items()
        ], None
    if plot_type == "cycling_efficiency":
        _require(table, spec.required_columns, plot_type)
        left = []
        charge = _values(rows, "cycle", "charge_specific_capacity_mAh_g")
        if charge:
            left.append(("Charge capacity", charge))
        left.append(("Discharge capacity", _values(rows, "cycle", "discharge_specific_capacity_mAh_g")))
        right = [("Coulombic efficiency", _values(rows, "cycle", "coulombic_efficiency_percent"))]
        return "Cycle number", "Specific capacity (mAh g-1)", left, ("Coulombic efficiency (%)", right)
    if plot_type == "rate_capability":
        _require(table, spec.required_columns, plot_type)
        return "Cycle number", "Discharge specific capacity (mAh g-1)", [
            ("Rate capability", _values(rows, "cycle", "discharge_specific_capacity_mAh_g"))
        ], None
    if plot_type == "dqdv":
        available = set(table.detected_columns)
        if "dQ_dV_mAh_g_V" in available:
            _require(table, ("voltage_V", "dQ_dV_mAh_g_V"), plot_type)
            points = _values(rows, "voltage_V", "dQ_dV_mAh_g_V")
        else:
            _require(table, ("voltage_V", "specific_capacity_mAh_g"), plot_type)
            raw = _values(rows, "voltage_V", "specific_capacity_mAh_g")
            points = []
            for left, right in zip(raw, raw[1:]):
                dv = right[0] - left[0]
                if abs(dv) > 1e-12:
                    points.append(((left[0] + right[0]) / 2.0, (right[1] - left[1]) / dv))
        return "Voltage (V)", "dQ/dV (mAh g-1 V-1)", [("dQ/dV", points)], None
    if plot_type == "cv_lsv":
        if "potential_V" not in table.detected_columns and "voltage_V" in table.detected_columns:
            rows = [dict(row, potential_V=row.get("voltage_V")) for row in rows]
        _require(PlotTable(table.source, tuple(rows), {**table.detected_columns, **({"potential_V": "voltage"} if "voltage_V" in table.detected_columns else {})}, table.detected_units, table.delimiter, table.encoding), spec.required_columns, plot_type)
        return "Potential (V)", "Current (mA)", [
            ("Scan {}".format(label), _values(group, "potential_V", "current_mA"))
            for label, group in _group(rows, "scan").items()
        ], None
    if plot_type == "eis_nyquist":
        _require(table, spec.required_columns, plot_type)
        raw = _values(rows, "z_real_ohm", "z_imag_ohm")
        points = [(x, -y if y < 0 else y) for x, y in raw]
        return "Z' (ohm)", "-Z'' (ohm)", [("Nyquist", points)], None
    if plot_type == "eis_bode":
        _require(table, spec.required_columns, plot_type)
        magnitude = [(math.log10(x), math.log10(y)) for x, y in _values(rows, "frequency_Hz", "z_magnitude_ohm") if x > 0 and y > 0]
        phase = [(math.log10(x), y) for x, y in _values(rows, "frequency_Hz", "phase_degree") if x > 0]
        return "log10 Frequency (Hz)", "log10 |Z| (ohm)", [("|Z|", magnitude)], ("Phase (degree)", [("Phase", phase)])
    if plot_type == "gitt_pitt":
        _require(table, spec.required_columns, plot_type)
        return "Time (h)", "Voltage (V)", [("GITT/PITT", [(x / 3600.0, y) for x, y in _values(rows, "time_s", "voltage_V")])], None
    if plot_type == "arrhenius":
        _require(table, spec.required_columns, plot_type)
        points = []
        for temperature, conductivity in _values(rows, "temperature_C", "conductivity_S_cm"):
            kelvin = temperature + 273.15
            if kelvin > 0 and conductivity > 0:
                points.append((1000.0 / kelvin, math.log10(conductivity)))
        return "1000/T (K-1)", "log10 Conductivity (S cm-1)", [("Conductivity", points)], None
    if plot_type == "dc_polarization":
        _require(table, spec.required_columns, plot_type)
        return "Time (s)", "Current (mA)", [("DC polarization", _values(rows, "time_s", "current_mA"))], None
    if plot_type == "ccd":
        _require(table, ("time_s", "voltage_V", "current_density_mA_cm2"), plot_type)
        return "Time (h)", "Voltage (V)", [("CCD", [(x / 3600.0, y) for x, y in _values(rows, "time_s", "voltage_V")])], None
    raise PlotDataError("未知图型：{}".format(plot_type))


def _bounds(series: Sequence[Tuple[str, Sequence[Tuple[float, float]]]]) -> Tuple[float, float, float, float]:
    points = [point for _, values in series for point in values]
    if len(points) < 2:
        raise PlotDataError("有效绘图点少于2个。")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    if xmin == xmax:
        xmin, xmax = xmin - 0.5, xmax + 0.5
    if ymin == ymax:
        ymin, ymax = ymin - 0.5, ymax + 0.5
    xpad = (xmax - xmin) * 0.04
    ypad = (ymax - ymin) * 0.08
    return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 10000 or abs(value) < 0.001:
        return "{:.2e}".format(value)
    return "{:.4g}".format(value)


def _render_svg(title: str, x_label: str, y_label: str, series, right_axis=None) -> str:
    width, height = 1000, 650
    left, right, top, bottom = 105, 90, 65, 90
    plot_w, plot_h = width - left - right, height - top - bottom
    xmin, xmax, ymin, ymax = _bounds(series)
    if right_axis is not None:
        right_label, right_series = right_axis
        _, _, rmin, rmax = _bounds(right_series)
    else:
        right_label, right_series, rmin, rmax = "", (), 0.0, 1.0

    def sx(value):
        return left + (value - xmin) / (xmax - xmin) * plot_w

    def sy(value, low=ymin, high=ymax):
        return top + (high - value) / (high - low) * plot_h

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g font-family="{}" fill="#222222">'.format(escape(FONT_FAMILY)),
        '<text x="500" y="34" text-anchor="middle" font-size="20" font-weight="600">{}</text>'.format(escape(title)),
    ]
    for index in range(6):
        fraction = index / 5.0
        x = left + fraction * plot_w
        y = top + fraction * plot_h
        xvalue = xmin + fraction * (xmax - xmin)
        yvalue = ymax - fraction * (ymax - ymin)
        parts.append('<line x1="{0:.2f}" y1="{1}" x2="{0:.2f}" y2="{2}" stroke="#E5E5E5" stroke-width="0.7"/>'.format(x, top, top + plot_h))
        parts.append('<line x1="{0}" y1="{1:.2f}" x2="{2}" y2="{1:.2f}" stroke="#E5E5E5" stroke-width="0.7"/>'.format(left, y, left + plot_w))
        parts.append('<line x1="{0:.2f}" y1="{1}" x2="{0:.2f}" y2="{2}" stroke="#222222" stroke-width="1"/>'.format(x, top + plot_h, top + plot_h - 7))
        parts.append('<text x="{:.2f}" y="{}" text-anchor="middle" font-size="13">{}</text>'.format(x, top + plot_h + 24, escape(_fmt(xvalue))))
        parts.append('<line x1="{0}" y1="{1:.2f}" x2="{2}" y2="{1:.2f}" stroke="#222222" stroke-width="1"/>'.format(left, y, left + 7))
        parts.append('<text x="{}" y="{:.2f}" text-anchor="end" dominant-baseline="middle" font-size="13">{}</text>'.format(left - 10, y, escape(_fmt(yvalue))))
        if right_axis is not None:
            rvalue = rmax - fraction * (rmax - rmin)
            parts.append('<text x="{}" y="{:.2f}" text-anchor="start" dominant-baseline="middle" font-size="13">{}</text>'.format(left + plot_w + 10, y, escape(_fmt(rvalue))))
    parts.extend([
        '<line x1="{0}" y1="{1}" x2="{2}" y2="{1}" stroke="#222222" stroke-width="{3}"/>'.format(left, top + plot_h, left + plot_w, AXIS_STROKE),
        '<line x1="{0}" y1="{1}" x2="{0}" y2="{2}" stroke="#222222" stroke-width="{3}"/>'.format(left, top, top + plot_h, AXIS_STROKE),
        '<text x="500" y="625" text-anchor="middle" font-size="16">{}</text>'.format(escape(x_label)),
        '<text x="25" y="{}" text-anchor="middle" font-size="16" transform="rotate(-90 25 {})">{}</text>'.format(top + plot_h / 2, top + plot_h / 2, escape(y_label)),
    ])
    if right_axis is not None:
        parts.extend([
            '<line x1="{0}" y1="{1}" x2="{0}" y2="{2}" stroke="#222222" stroke-width="{3}"/>'.format(left + plot_w, top, top + plot_h, AXIS_STROKE),
            '<text x="975" y="{}" text-anchor="middle" font-size="16" transform="rotate(90 975 {})">{}</text>'.format(top + plot_h / 2, top + plot_h / 2, escape(right_label)),
        ])

    legend_x, legend_y = left + 15, top + 18
    all_series = list(series) + list(right_series)
    for index, (label, points) in enumerate(all_series):
        if not points:
            continue
        color = NATURE_COLORS[index % len(NATURE_COLORS)]
        low, high = (rmin, rmax) if index >= len(series) and right_axis is not None else (ymin, ymax)
        coordinates = " ".join("{:.2f},{:.2f}".format(sx(x), sy(y, low, high)) for x, y in points)
        parts.append('<polyline points="{}" fill="none" stroke="{}" stroke-width="{}" stroke-linejoin="round" stroke-linecap="round"/>'.format(coordinates, color, DATA_STROKE))
        for x, y in points:
            parts.append('<circle cx="{:.2f}" cy="{:.2f}" r="3.2" fill="#FFFFFF" stroke="{}" stroke-width="1.6"/>'.format(sx(x), sy(y, low, high), color))
        ly = legend_y + index * 22
        parts.append('<line x1="{0}" y1="{1}" x2="{2}" y2="{1}" stroke="{3}" stroke-width="2"/>'.format(legend_x, ly, legend_x + 28, color))
        parts.append('<text x="{}" y="{}" dominant-baseline="middle" font-size="13">{}</text>'.format(legend_x + 36, ly, escape(str(label))))
    parts.extend(["</g>", "</svg>"])
    return "\n".join(parts) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_electrochemical_plot(plot_type: str, input_path: Path, output_dir: Path) -> PlotResult:
    if plot_type not in PLOT_SPECS:
        raise PlotDataError("不支持的图型：{}".format(plot_type))
    table = load_plot_table(input_path)
    x_label, y_label, series, right_axis = _series_for(plot_type, table)
    point_count = sum(len(points) for _, points in series)
    if right_axis is not None:
        point_count += sum(len(points) for _, points in right_axis[1])
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    spec = PLOT_SPECS[plot_type]
    svg_path = target / (plot_type + "_nature.svg")
    svg_path.write_text(_render_svg(spec.label, x_label, y_label, series, right_axis), encoding="utf-8")
    audit_path = target / (plot_type + "_plot_record.json")
    audit_path.write_text(
        json.dumps(
            {
                "plot_type": plot_type,
                "label": spec.label,
                "source_file": table.source.name,
                "source_sha256": _sha256(table.source),
                "detected_columns": dict(table.detected_columns),
                "canonical_units": dict(table.detected_units),
                "point_count": point_count,
                "theme": "Nature-inspired v1 (Arial, white background, restrained strokes, NPG colourblind-aware palette)",
                "scientific_question": spec.scientific_question,
                "limitations": spec.limitations,
                "reference_dois": list(spec.reference_dois),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return PlotResult(plot_type, svg_path, audit_path, point_count)
