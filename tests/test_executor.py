import json
import os
import unittest
from unittest.mock import patch

from anton.executor import FakeExecutor
from anton.executor.opencode_executor import OpenCodeExecutor
from anton.executor.pi_executor import DEFAULT_TOOLS, PiExecutor


class TestExecutorContract(unittest.TestCase):
    def test_fake_executor_contract(self):
        res = FakeExecutor().run("hello", model="m", provider="local")
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(res.output.startswith("[fake]"))
        self.assertIsNone(res.tokens_in)  # local provider: no usage
        self.assertGreaterEqual(res.duration_ms, 0)


class TestPiExecutor(unittest.TestCase):
    def test_default_tools_are_read_only(self):
        # Nothing upstream of PiExecutor restricts what a dispatched task can
        # do (governor.py only gates *whether* to dispatch); the default must
        # stay read-only so a fresh install isn't handing auto-executed jobs
        # unrestricted bash/edit/write access out of the box.
        self.assertEqual(DEFAULT_TOOLS, "read,grep,find,ls")
        self.assertEqual(PiExecutor().tools, DEFAULT_TOOLS)
        for destructive in ("bash", "edit", "write"):
            self.assertNotIn(destructive, DEFAULT_TOOLS.split(","))

    @patch("anton.executor.pi_executor.shutil.which", return_value="/usr/bin/pi")
    @patch("anton.executor.pi_executor.subprocess.run")
    def test_run_passes_tools_flag_to_pi(self, mock_run, _mock_which):
        mock_run.return_value = type(
            "P", (), {"returncode": 0, "stdout": "ok", "stderr": ""},
        )()
        PiExecutor(tools="read,grep").run("task", model="m", provider="p")
        args = mock_run.call_args.args[0]
        self.assertIn("--tools", args)
        self.assertEqual(args[args.index("--tools") + 1], "read,grep")

    @patch("anton.executor.pi_executor.shutil.which", return_value=None)
    def test_unavailable_binary_fails_loud_not_silent(self, _mock_which):
        res = PiExecutor().run("task", model="m", provider="p")
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(res.error, "ENOENT")


class TestOpenCodeExecutor(unittest.TestCase):
    @patch("anton.executor.opencode_executor.shutil.which", return_value=None)
    def test_unavailable_binary_fails_loud_not_silent(self, _mock_which):
        res = OpenCodeExecutor().run("task", model="opencode-go/deepseek-v4-flash", provider="cloud")
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(res.error, "ENOENT")

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_run_passes_model_and_format_flags(self, mock_run, _mock_which):
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        OpenCodeExecutor().run("do the thing", model="opencode-go/deepseek-v4-flash", provider="cloud")
        args = mock_run.call_args.args[0]
        self.assertIn("run", args)
        self.assertIn("do the thing", args)
        self.assertEqual(args[args.index("--model") + 1], "opencode-go/deepseek-v4-flash")
        self.assertEqual(args[args.index("--format") + 1], "json")

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_parses_text_and_usage_from_json_event_stream(self, mock_run, _mock_which):
        events = [
            {"type": "step_start", "part": {"type": "step-start"}},
            {"type": "text", "part": {"type": "text", "text": "ANTON_LIVE_TEST_OK"}},
            {"type": "step_finish", "part": {"type": "step-finish",
             "tokens": {"input": 100, "output": 20}, "cost": 0.0042}},
        ]
        stdout = "\n".join(json.dumps(e) for e in events)
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        res = OpenCodeExecutor().run("task", model="opencode-go/deepseek-v4-flash", provider="cloud")
        self.assertEqual(res.output, "ANTON_LIVE_TEST_OK")
        self.assertEqual(res.tokens_in, 100)
        self.assertEqual(res.tokens_out, 20)
        self.assertEqual(res.cost_usd, 0.0042)

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_non_json_lines_are_skipped_not_fatal(self, mock_run, _mock_which):
        stdout = "not json\n" + json.dumps(
            {"type": "text", "part": {"type": "text", "text": "ok"}})
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        res = OpenCodeExecutor().run("task", model="m", provider="p")
        self.assertEqual(res.output, "ok")

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_no_playwright_profile_passes_no_env_override(self, mock_run, _mock_which):
        # the common case (default executor, no browser work) must not pay
        # any MCP-config cost or touch the inherited environment at all.
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        OpenCodeExecutor().run("task", model="m", provider="p")
        self.assertIsNone(mock_run.call_args.kwargs["env"])

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_playwright_profile_registers_a_local_mcp_server_scoped_to_it(self, mock_run, _mock_which):
        import json as json_mod
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        executor = OpenCodeExecutor(playwright_profile_dir="/data/browser-sessions/quickbooks")
        executor.run("check the balance", model="m", provider="p")
        env = mock_run.call_args.kwargs["env"]
        self.assertIsNotNone(env)
        config_home = env["XDG_CONFIG_HOME"]
        with open(os.path.join(config_home, "opencode", "opencode.json")) as f:
            config = json_mod.load(f)
        mcp = config["mcp"]["playwright"]
        self.assertEqual(mcp["type"], "local")
        self.assertIn("/data/browser-sessions/quickbooks", mcp["command"])
        self.assertIn("--user-data-dir", mcp["command"])
        # the rest of the real environment (e.g. a wizard-saved provider key)
        # passes through untouched -- only XDG_CONFIG_HOME is overridden.
        self.assertEqual(env["PATH"], os.environ["PATH"])

    @patch("anton.executor.opencode_executor.shutil.which", return_value="/usr/bin/opencode")
    @patch("anton.executor.opencode_executor.subprocess.run")
    def test_scoped_config_is_written_once_and_reused_across_calls(self, mock_run, _mock_which):
        mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        executor = OpenCodeExecutor(playwright_profile_dir="/data/browser-sessions/quickbooks")
        executor.run("first", model="m", provider="p")
        first_config_home = mock_run.call_args.kwargs["env"]["XDG_CONFIG_HOME"]
        executor.run("second", model="m", provider="p")
        second_config_home = mock_run.call_args.kwargs["env"]["XDG_CONFIG_HOME"]
        self.assertEqual(first_config_home, second_config_home)
