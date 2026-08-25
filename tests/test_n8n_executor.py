"""N8NExecutor: dispatches to one n8n workflow's webhook, maps its response
back into a RunResult. Real HTTP is injected so CI never touches the
network -- same discipline as tests/authz/test_qbo_oauth.py's fake_intuit."""
import json
import unittest

from anton.executor.n8n_executor import N8NExecutor


def fake_post(status=200, body=None, raises=None):
    calls = []

    def transport(url, payload, headers, timeout_s):
        calls.append({"url": url, "payload": payload, "headers": headers, "timeout_s": timeout_s})
        if raises is not None:
            raise raises
        return status, json.dumps(body if body is not None else {})

    transport.calls = calls
    return transport


def fake_get(status=200, raises=None):
    calls = []

    def transport(url, timeout_s):
        calls.append({"url": url, "timeout_s": timeout_s})
        if raises is not None:
            raise raises
        return status

    transport.calls = calls
    return transport


class TestN8NExecutorRun(unittest.TestCase):
    def test_successful_dispatch_maps_response_into_run_result(self):
        post = fake_post(200, {"output": "did the thing", "exit_code": 0})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("do it", model="m", provider="p", timeout_s=30)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "did the thing")
        self.assertEqual(result.model, "m")
        self.assertEqual(result.provider, "p")
        self.assertIsNone(result.error)

    def test_sends_task_model_provider_as_the_webhook_payload(self):
        post = fake_post(200, {"output": "ok"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        ex.run("reconcile stripe vs qbo", model="anthropic/claude", provider="cloud", timeout_s=10)
        call = post.calls[0]
        self.assertEqual(call["url"], "https://n8n.example/webhook/abc")
        self.assertEqual(call["payload"], {
            "task": "reconcile stripe vs qbo", "model": "anthropic/claude", "provider": "cloud",
        })
        self.assertEqual(call["timeout_s"], 10)

    def test_api_key_sent_as_header_when_configured(self):
        post = fake_post(200, {"output": "ok"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", api_key="secret-key", post_transport=post)
        ex.run("x", model="m", provider="p")
        self.assertEqual(post.calls[0]["headers"], {"X-N8N-Api-Key": "secret-key"})

    def test_no_api_key_sends_no_auth_header(self):
        post = fake_post(200, {"output": "ok"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        ex.run("x", model="m", provider="p")
        self.assertEqual(post.calls[0]["headers"], {})

    def test_non_200_response_is_a_failed_run_not_an_exception(self):
        post = fake_post(500, {"message": "workflow error"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("x", model="m", provider="p")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.error, "http_500")

    def test_connection_failure_is_a_failed_run_not_a_raised_exception(self):
        post = fake_post(raises=ConnectionError("refused"))
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("x", model="m", provider="p")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.error, "ConnectionError")

    def test_non_json_response_body_is_a_failed_run(self):
        post = lambda *a, **k: (200, "<html>not json</html>")  # noqa: E731
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("x", model="m", provider="p")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.error, "bad_response")

    def test_missing_exit_code_defaults_to_zero(self):
        post = fake_post(200, {"output": "fine, no explicit exit_code"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("x", model="m", provider="p")
        self.assertEqual(result.exit_code, 0)

    def test_error_field_surfaces_as_stderr(self):
        post = fake_post(200, {"output": "", "exit_code": 1, "error": "gate rejected"})
        ex = N8NExecutor("https://n8n.example/webhook/abc", post_transport=post)
        result = ex.run("x", model="m", provider="p")
        self.assertEqual(result.stderr, "gate rejected")


class TestN8NExecutorAvailable(unittest.TestCase):
    def test_available_true_on_200_health_check(self):
        ex = N8NExecutor("https://n8n.example/webhook/abc", get_transport=fake_get(200))
        self.assertTrue(ex.available())

    def test_available_false_on_non_200(self):
        ex = N8NExecutor("https://n8n.example/webhook/abc", get_transport=fake_get(503))
        self.assertFalse(ex.available())

    def test_available_false_on_connection_error_not_a_raised_exception(self):
        ex = N8NExecutor("https://n8n.example/webhook/abc", get_transport=fake_get(raises=OSError("down")))
        self.assertFalse(ex.available())

    def test_default_health_url_derived_from_webhook_origin(self):
        get = fake_get(200)
        ex = N8NExecutor("https://n8n.example:5678/webhook/abc123", get_transport=get)
        ex.available()
        self.assertEqual(get.calls[0]["url"], "https://n8n.example:5678/healthz")

    def test_explicit_health_url_overrides_the_default(self):
        get = fake_get(200)
        ex = N8NExecutor("https://n8n.example/webhook/abc", health_url="https://shared.example/ping",
                         get_transport=get)
        ex.available()
        self.assertEqual(get.calls[0]["url"], "https://shared.example/ping")


if __name__ == "__main__":
    unittest.main()
