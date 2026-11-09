from __future__ import annotations

import unittest

from electrochem_harness_v2.theoretical_energy import derive_theoretical_energy


class TheoryModelTests(unittest.TestCase):
    def test_uses_reaction_formula_alias_and_measured_voltage_when_theoretical_voltage_missing(self):
        model = {
            "hypothetical_discharge_reaction": "P2O5 + 16 Li+ + 16 e- -> 2 Li3P + 5 Li2O",
            "electron_transfer_per_P2O5": 16,
            "average_voltage_V": None,
            "source_urls": ["https://example.org/source"],
            "limitations": "candidate reaction",
        }
        analysis = {"gcd_summary": {"first_complete_average_discharge_voltage_V": 1.5}}
        result = derive_theoretical_energy(model, analysis)
        self.assertEqual(result["formula"], "P2O5")
        self.assertEqual(result["electron_transfer_mol_e_per_mol"], 16.0)
        self.assertEqual(result["voltage_basis"], "measured_first_complete_cycle")
        self.assertEqual(result["status"], "candidate_reaction_hybrid_energy_estimate")
        self.assertAlmostEqual(result["theoretical_specific_capacity_mAh_g"], 3020.8, delta=3.0)


if __name__ == "__main__":
    unittest.main()
