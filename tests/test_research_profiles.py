import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ResearchProfileStoreTests(unittest.TestCase):
    def test_profiles_persist_without_raw_data_or_output_paths(self):
        from electrochem_harness.research_profiles import ResearchProfileStore

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profiles.json"
            store = ResearchProfileStore(path)
            name = store.save(
                "锂硫高温体系",
                {
                    "battery_system": "锂硫电池",
                    "active_material": "P2S5/S 1:1，复合正极中占70%",
                    "test_current": "0.2",
                    "temperature": "60",
                    "research_domain": "固态锂硫电池",
                    "research_background": "研究转化过程。",
                    "research_question": "哪些因素影响放电电压和比容量？",
                    "input_file": "private.csv",
                    "output_dir": "private-output",
                },
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            restored = ResearchProfileStore(path)
            active_name = restored.active_name()
            active = restored.active()

        self.assertEqual(name, "锂硫高温体系")
        self.assertEqual(active_name, name)
        self.assertEqual(active["temperature"], "60")
        self.assertNotIn("input_file", payload["profiles"][name]["values"])
        self.assertNotIn("output_dir", payload["profiles"][name]["values"])

    def test_multiple_profiles_can_be_selected_and_deleted(self):
        from electrochem_harness.research_profiles import ResearchProfileStore

        with tempfile.TemporaryDirectory() as temp:
            store = ResearchProfileStore(Path(temp) / "profiles.json")
            store.save("体系A", {"battery_system": "A"})
            store.save("体系B", {"battery_system": "B"})
            store.set_active("体系A")
            self.assertEqual(store.active()["battery_system"], "A")
            store.delete("体系A")

            self.assertEqual(store.names(), ("体系B",))
            self.assertEqual(store.active_name(), "体系B")


if __name__ == "__main__":
    unittest.main()
