import unittest
from relaylens.privacy import private_report


class PrivacyTests(unittest.TestCase):
    def test_secrets_paths_urls_and_ip_are_removed(self):
        report = {"api_key":"AUTH_EXAMPLE_123", "base_url":"https://provider.example/v1",
                  "detail":"AUTH_EXAMPLE_123 C:\\Users\\example\\project 192.0.2.10"}
        text = str(private_report(report, ("AUTH_EXAMPLE_123",)))
        for needle in ("AUTH_EXAMPLE_123", "provider.example", "C:\\Users\\example", "192.0.2.10"):
            self.assertNotIn(needle, text)


if __name__ == "__main__": unittest.main()
