import http.client
import unittest
from anton.oauth import CallbackServer


class TestOAuth(unittest.TestCase):
    def test_callback_captures_code(self):
        srv = CallbackServer(port=0, timeout_s=10)
        srv.start()
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
        conn.request("GET", "/callback?code=abc123&state=xyz")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        result = srv.wait()
        srv.stop()
        self.assertEqual(result["code"], "abc123")
        self.assertEqual(result["state"], "xyz")
