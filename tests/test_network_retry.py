from __future__ import annotations

from email.message import Message
import unittest
from urllib.error import HTTPError, URLError

from electrochem_harness_v2.search import LiteratureSearchAdapter


def http_error(status: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.test", status, "failure", headers, None)


class NetworkRetryTests(unittest.TestCase):
    def test_retries_connection_failure_with_bounded_exponential_backoff(self):
        attempts = 0
        sleeps: list[float] = []

        def transport(_url: str) -> dict:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise URLError("offline")
            return {"message": {"items": []}}

        result = LiteratureSearchAdapter(
            transport=transport,
            max_attempts=3,
            backoff_base_seconds=3,
            max_backoff_seconds=4,
            sleep=sleeps.append,
        ).search(["battery"])

        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [3, 4])
        self.assertEqual(result.source_status["Crossref"], {"attempts": 3, "status": "success", "error": None})

    def test_non_retryable_http_error_stops_after_one_attempt(self):
        attempts = 0
        sleeps: list[float] = []

        def transport(_url: str) -> dict:
            nonlocal attempts
            attempts += 1
            raise http_error(403)

        result = LiteratureSearchAdapter(
            transport=transport,
            max_attempts=4,
            sleep=sleeps.append,
        ).search(["battery"])

        self.assertEqual(attempts, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(result.source_status["Crossref"]["attempts"], 1)
        self.assertEqual(result.source_status["Crossref"]["status"], "error")
        self.assertIn("HTTP Error 403", result.source_status["Crossref"]["error"])
        self.assertIn("Crossref HTTPError", result.error)

    def test_retry_after_seconds_is_honored(self):
        sleeps: list[float] = []
        attempts = 0

        def transport(_url: str) -> dict:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise http_error(429, "2.5")
            return {"message": {"items": []}}

        LiteratureSearchAdapter(
            transport=transport,
            max_attempts=2,
            max_backoff_seconds=10,
            sleep=sleeps.append,
        ).search(["battery"])

        self.assertEqual(sleeps, [2.5])

    def test_each_source_has_independent_attempts_and_final_error(self):
        crossref_attempts = 0
        openalex_attempts = 0

        def crossref(_url: str) -> dict:
            nonlocal crossref_attempts
            crossref_attempts += 1
            raise TimeoutError("crossref timed out")

        def openalex(_url: str) -> dict:
            nonlocal openalex_attempts
            openalex_attempts += 1
            raise http_error(404)

        result = LiteratureSearchAdapter(
            transport=crossref,
            openalex_transport=openalex,
            max_attempts=2,
            sleep=lambda _seconds: None,
        ).search(["battery"])

        self.assertEqual(crossref_attempts, 2)
        self.assertEqual(openalex_attempts, 1)
        self.assertEqual(result.source_status["Crossref"]["attempts"], 2)
        self.assertIn("crossref timed out", result.source_status["Crossref"]["error"])
        self.assertEqual(result.source_status["OpenAlex"]["attempts"], 1)
        self.assertIn("HTTP Error 404", result.source_status["OpenAlex"]["error"])


if __name__ == "__main__":
    unittest.main()
