"""Auditable active-material theoretical capacity and energy calculations."""
from __future__ import annotations

import math
import re


FARADAY_CONSTANT_C_MOL = 96485.33212
ATOMIC_WEIGHTS = {
    "H": 1.008, "Li": 6.94, "B": 10.81, "C": 12.011, "N": 14.007, "O": 15.999,
    "F": 18.998403, "Na": 22.98977, "Mg": 24.305, "Al": 26.98154, "P": 30.973762,
    "S": 32.06, "Cl": 35.45, "K": 39.0983, "Ca": 40.078, "Ti": 47.867, "V": 50.9415,
    "Cr": 51.9961, "Mn": 54.938044, "Fe": 55.845, "Co": 58.933194, "Ni": 58.6934,
    "Cu": 63.546, "Zn": 65.38, "Ga": 69.723, "Ge": 72.630, "Br": 79.904,
    "Zr": 91.224, "Nb": 92.90637, "Mo": 95.95, "In": 114.818, "Sn": 118.710,
    "I": 126.90447, "La": 138.90547, "Ce": 140.116, "Ta": 180.94788, "W": 183.84,
}
_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*(?:\.\d+)?)")


def molar_mass(formula: str) -> float:
    clean = str(formula or "").replace(" ", "")
    matches = list(_TOKEN.finditer(clean))
    if not clean or not matches or "".join(match.group(0) for match in matches) != clean:
        raise ValueError("Only simple chemical formulae without parentheses are supported.")
    total = 0.0
    for match in matches:
        element = match.group(1)
        if element not in ATOMIC_WEIGHTS:
            raise ValueError("Unknown element in formula: {}".format(element))
        count = float(match.group(2) or 1)
        total += ATOMIC_WEIGHTS[element] * count
    return total


def calculate_theoretical_energy(formula: str, electron_transfer: float, average_voltage_V: float) -> dict:
    electrons = float(electron_transfer)
    voltage = float(average_voltage_V)
    if not math.isfinite(electrons) or electrons <= 0:
        raise ValueError("Electron transfer must be a positive finite number.")
    if not math.isfinite(voltage) or voltage <= 0:
        raise ValueError("Average discharge voltage must be a positive finite number.")
    mass = molar_mass(formula)
    capacity = electrons * FARADAY_CONSTANT_C_MOL / (3.6 * mass)
    return {
        "formula": formula,
        "molar_mass_g_mol": mass,
        "electron_transfer_mol_e_per_mol": electrons,
        "average_discharge_voltage_V": voltage,
        "theoretical_specific_capacity_mAh_g": capacity,
        "theoretical_specific_energy_Wh_kg": capacity * voltage,
        "basis": "active_material_only",
        "formulae": {
            "capacity": "nF/(3.6M)",
            "energy": "specific_capacity_mAh_g × average_discharge_voltage_V",
        },
        "limitations": [
            "该数值只按活性物质质量计算，不是正极复合层、电芯或电池包能量密度。",
            "电子转移数和平均放电电压必须来自经审核的反应模型或实验依据。",
        ],
    }


def derive_theoretical_energy(model: dict, analysis: dict) -> dict:
    """Normalize a reviewed/candidate reaction model and calculate with an explicit voltage basis."""
    reaction = str(model.get("hypothetical_discharge_reaction") or model.get("reaction") or "")
    formula = str(model.get("formula") or "").strip()
    if not re.fullmatch(r"(?:[A-Z][a-z]?\d*(?:\.\d+)?)+", formula):
        left = reaction.split("+", 1)[0].strip().replace(" ", "")
        formula = left if re.fullmatch(r"(?:[A-Z][a-z]?\d*(?:\.\d+)?)+", left) else ""
    electrons = model.get("electron_transfer")
    if electrons in (None, ""):
        electrons = model.get("electron_transfer_per_P2O5") or model.get("electron_transfer_per_formula_unit")
    voltage = model.get("average_voltage_V")
    voltage_basis = "literature_theoretical_or_reported_average"
    if voltage in (None, ""):
        summary = analysis.get("gcd_summary") or {}
        voltage = summary.get("first_complete_average_discharge_voltage_V")
        voltage_basis = "measured_first_complete_cycle"
    if not formula or electrons in (None, ""):
        raise ValueError("Codex reaction candidate lacks a simple formula or electron-transfer number.")
    if voltage in (None, ""):
        capacity_only = calculate_theoretical_energy(formula, electrons, 1.0)
        capacity_only["theoretical_specific_energy_Wh_kg"] = None
        capacity_only["average_discharge_voltage_V"] = None
        capacity_only["status"] = "candidate_reaction_capacity_only"
        capacity_only["voltage_basis"] = "missing"
        return capacity_only
    result = calculate_theoretical_energy(formula, electrons, voltage)
    result["status"] = "candidate_reaction_hybrid_energy_estimate" if voltage_basis.startswith("measured") else "candidate_reaction_energy_estimate"
    result["voltage_basis"] = voltage_basis
    result["reaction_candidate"] = reaction or None
    result["source_urls"] = list(model.get("source_urls") or [])
    limitations = model.get("limitations") or []
    result["model_limitations"] = [limitations] if isinstance(limitations, str) else list(limitations)
    return result
