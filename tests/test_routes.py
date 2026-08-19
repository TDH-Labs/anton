import unittest
from anton.routes import is_cloud, select_route


class TestRoutes(unittest.TestCase):
    def test_local_first_default(self):
        r = select_route()
        self.assertEqual(r.provider, "local")
        self.assertIn("[REDACTED-LOCAL-INFERENCE]", r.model)
        self.assertIn("openrouter", r.fallback)

    def test_cloud_preference(self):
        r = select_route(prefer="cloud")
        self.assertEqual(r.provider, "cloud")
        self.assertTrue(is_cloud(r))

    def test_fallback_model_is_cloud(self):
        r = select_route()
        self.assertIn("openrouter", r.fallback)  # fallback is a cloud model string
