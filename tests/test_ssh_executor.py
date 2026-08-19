import os
import stat
import tempfile
import unittest
from harbor.executor.ssh_executor import SSHExecutor


class TestSSHExecutor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        # fake ssh: print args to stdout, exit 0, so we can assert the command line
        self.ssh = os.path.join(self.dir.name, "fake-ssh")
        with open(self.ssh, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
        os.chmod(self.ssh, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    def tearDown(self):
        self.dir.cleanup()

    def test_builds_ssh_command(self):
        exe = SSHExecutor(host="10.9.9.9", user="umbrel", key="/keys/id",
                          command="run-local-recipe.sh <recipe>", ssh_bin=self.ssh)
        res = exe.run("bill-capture", model="[REDACTED-LOCAL-INFERENCE]/q", provider="local")
        self.assertEqual(res.exit_code, 0)
        self.assertIn("-i", res.output.splitlines()[0] if res.output else "")
        joined = " ".join(res.output.splitlines())
        self.assertIn("umbrel@10.9.9.9", joined)
        self.assertIn("run-local-recipe.sh bill-capture", joined)

    def test_unavailable_without_host(self):
        exe = SSHExecutor(host="", ssh_bin=self.ssh)
        res = exe.run("x", model="m", provider="local")
        self.assertEqual(res.exit_code, 1)
        self.assertIn("unavailable", res.error or "")

    def test_command_injection_escaped(self):
        exe = SSHExecutor(host="10.9.9.9", user="umbrel",
                          command="run-local-recipe.sh <recipe>", ssh_bin=self.ssh)
        res = exe.run("bill-capture; rm -rf /", model="m", provider="local")
        self.assertEqual(res.exit_code, 0)
        joined = " ".join(res.output.splitlines())
        self.assertIn("'bill-capture; rm -rf /'", joined)

