"""Map detected electrochemical metrics to auditable literature benchmark topics."""
from __future__ import annotations


def build_benchmark_topics(system_keywords: str, analysis: dict) -> list[str]:
    prefix = " ".join(str(system_keywords or "").split())
    summary = analysis.get("gcd_summary") or {}
    topics = [
        "{} peer-reviewed SCI primary research Google Scholar solid-state battery cathode specific capacity".format(prefix),
        "{} peer-reviewed SCI primary research Google Scholar average discharge voltage polarization".format(prefix),
        "{} X-MOL 中文学术文献 P2O5 LPSC 固态电池 机理与电化学表征".format(prefix),
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

    ignored = {"row_count", "negative_voltage_count", "repeated_or_reversed_time_pairs", "start_source_row", "end_source_row"}
    for path in sorted(set(walk(analysis))):
        key = path.rsplit(".", 1)[-1]
        if key in ignored or key.startswith(("latest_", "first_")):
            continue
        if key.endswith(("_V", "_percent", "_mAh_g", "_S_cm", "_ohm", "_ohm_cm2", "_eV", "_mA_cm2")):
            topics.append("{} {} peer-reviewed SCI literature".format(prefix, key.replace("_", " ")))
    return list(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
