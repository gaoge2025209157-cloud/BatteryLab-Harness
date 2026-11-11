"""Map deterministic electrochemical metrics to method-specific literature topics."""
from __future__ import annotations


def build_benchmark_topics(system_keywords: str, analysis: dict, analysis_type: str = "gcd") -> list[str]:
    """Return auditable search topics without importing another method's claims."""
    prefix = " ".join(str(system_keywords or "").split())
    method = str(analysis_type or "gcd").strip().casefold()
    if method == "cv":
        topics = [
            "{} peer-reviewed SCI cyclic voltammetry redox peaks scan rate reversibility".format(prefix),
            "{} peer-reviewed SCI cyclic voltammetry electrochemical window peak separation".format(prefix),
            "{} X-MOL 中文学术文献 循环伏安 氧化还原峰 扫描速率".format(prefix),
        ]
    elif method == "eis":
        topics = [
            "{} peer-reviewed SCI electrochemical impedance spectroscopy Nyquist frequency response".format(prefix),
            "{} peer-reviewed SCI charge transfer resistance impedance interpretation validation".format(prefix),
            "{} X-MOL 中文学术文献 电化学阻抗 频率响应 界面过程".format(prefix),
        ]
    elif method == "gitt":
        topics = [
            "{} peer-reviewed SCI GITT pulse relaxation voltage transient protocol interpretation".format(prefix),
            "{} peer-reviewed SCI galvanostatic intermittent titration experimental controls".format(prefix),
            "{} X-MOL 中文学术文献 GITT 脉冲 松弛 电压响应".format(prefix),
        ]
    else:
        summary = analysis.get("gcd_summary") or {}
        topics = [
            "{} peer-reviewed SCI primary research Google Scholar electrochemical specific capacity".format(prefix),
            "{} peer-reviewed SCI primary research Google Scholar average discharge voltage polarization".format(prefix),
            "{} X-MOL 中文学术文献 电化学机理与材料表征".format(prefix),
            "{} peer-reviewed SCI theoretical specific capacity and theoretical specific energy Wh kg reaction mechanism".format(prefix),
        ]
        if summary.get("latest_polarization_voltage_V") is not None:
            topics.append("{} peer-reviewed SCI charge discharge voltage hysteresis polarization".format(prefix))
        if summary.get("latest_coulombic_efficiency_percent") is not None:
            topics.append("{} peer-reviewed SCI coulombic efficiency reversibility".format(prefix))
        if summary.get("latest_capacity_retention_percent") is not None:
            topics.append("{} peer-reviewed SCI capacity retention cycling stability".format(prefix))

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, nested in value.items():
                name = "{}.{}".format(path, key) if path else key
                yield from walk(nested, name)
        elif isinstance(value, (int, float)) and path:
            yield path

    ignored = {
        "row_count", "point_count", "negative_voltage_count", "repeated_or_reversed_time_pairs",
        "start_source_row", "end_source_row",
    }
    allowed_suffixes = {
        "gcd": ("_V", "_percent", "_mAh_g", "_S_cm", "_ohm", "_ohm_cm2", "_eV", "_mA_cm2"),
        "cv": ("_V", "_V_s", "_A", "_percent"),
        "eis": ("_Hz", "_ohm", "_percent"),
        # Do not turn a GITT descriptive packet into an automatic diffusion claim.
        "gitt": ("_V", "_A", "_s", "_percent"),
    }.get(method, ("_V", "_percent"))
    for path in sorted(set(walk(analysis))):
        key = path.rsplit(".", 1)[-1]
        if key in ignored or key.startswith(("latest_", "first_")):
            continue
        if key.endswith(allowed_suffixes):
            topics.append("{} {} {} peer-reviewed SCI literature".format(prefix, method.upper(), key.replace("_", " ")))
    return list(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
