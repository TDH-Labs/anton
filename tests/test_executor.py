import unittest
from harbor.executor import FakeExecutor


class TestExecutorContract(unittest.TestCase):
    def test_fake_executor_contract(self):
        res = FakeExecutor().run("hello", model="m", provider="local")
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(res.output.startswith("[fake]"))
        self.assertIsNone(res.tokens_in)  # local provider: no usage
        self.assertGreaterEqual(res.duration_ms, 0)
