from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from electrochem_harness_v2.cache_policy import CachePolicy, classify_cache_entry, create_cache_entry


INPUTS = {
    "prompt": "summarize",
    "adapter": "crossref-v1",
    "model": "model-a",
    "context": {"project": "battery"},
    "topic": ["electrolyte"],
}


class CachePolicyTests(unittest.TestCase):
    def test_entry_contains_version_timestamps_ttl_and_all_fingerprints(self):
        now = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
        entry = create_cache_entry({"records": []}, ttl_seconds=90, now=now, **INPUTS)

        self.assertEqual(entry["schema_version"], 1)
        self.assertEqual(entry["created_at"], now.isoformat())
        self.assertEqual(entry["expires_at"], (now + timedelta(seconds=90)).isoformat())
        self.assertEqual(entry["ttl_seconds"], 90)
        self.assertEqual(set(entry["fingerprints"]), {"prompt", "adapter", "model", "context", "topic"})

    def test_fresh_becomes_stale_at_expiration(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        entry = create_cache_entry({}, ttl_seconds=60, now=now, **INPUTS)

        self.assertEqual(classify_cache_entry(entry, now=now + timedelta(seconds=59), **INPUTS), "fresh")
        self.assertEqual(classify_cache_entry(entry, now=now + timedelta(seconds=60), **INPUTS), "stale")

    def test_legacy_unversioned_entry_is_incompatible(self):
        self.assertEqual(classify_cache_entry({"payload": {}}, **INPUTS), "incompatible")

    def test_each_fingerprint_change_is_incompatible(self):
        entry = create_cache_entry({}, **INPUTS)
        for field in INPUTS:
            changed = dict(INPUTS)
            changed[field] = "changed"
            with self.subTest(field=field):
                self.assertEqual(classify_cache_entry(entry, **changed), "incompatible")

    def test_sensitive_payload_fields_are_not_cached(self):
        entry = CachePolicy().create(
            {"OPENAI_API_KEY": "key-value", "nested": {"authorization": "Bearer secret", "safe": 1}},
            **INPUTS,
        )
        serialized = json.dumps(entry)

        self.assertNotIn("key-value", serialized)
        self.assertNotIn("Bearer secret", serialized)
        self.assertEqual(entry["payload"], {"nested": {"safe": 1}})

    def test_default_ttl_can_be_overridden_on_policy(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        entry = CachePolicy(ttl_seconds=12).create({}, now=now, **INPUTS)
        self.assertEqual(entry["ttl_seconds"], 12)


if __name__ == "__main__":
    unittest.main()
