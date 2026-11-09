from __future__ import annotations

import unittest

from electrochem_harness_v2.theoretical_energy import calculate_theoretical_energy, molar_mass


class TheoreticalEnergyTests(unittest.TestCase):
    def test_calculates_active_material_theoretical_capacity_and_energy(self):
        result = calculate_theoretical_energy("P2O5", electron_transfer=10, average_voltage_V=1.5)
        self.assertAlmostEqual(molar_mass("P2O5"), 141.94, places=1)
        self.assertAlmostEqual(result["theoretical_specific_capacity_mAh_g"], 1888.0, delta=2.0)
        self.assertAlmostEqual(result["theoretical_specific_energy_Wh_kg"], 2832.0, delta=4.0)
        self.assertEqual(result["basis"], "active_material_only")

    def test_calculates_user_confirmed_p2o5_sixteen_electron_model(self):
        result = calculate_theoretical_energy("P2O5", electron_transfer=16, average_voltage_V=1.5)
        self.assertAlmostEqual(result["theoretical_specific_capacity_mAh_g"], 3020.8, delta=2.0)
        self.assertAlmostEqual(result["theoretical_specific_energy_Wh_kg"], 4531.2, delta=4.0)

        with self.assertRaises(ValueError):
            calculate_theoretical_energy("P2O5", electron_transfer=0, average_voltage_V=1.5)
        with self.assertRaises(ValueError):
            calculate_theoretical_energy("P2O5", electron_transfer=10, average_voltage_V=-1)


if __name__ == "__main__":
    unittest.main()
