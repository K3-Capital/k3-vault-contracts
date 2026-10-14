"""Offline verification-wrapper regressions; never use repository dotenv or live tools."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADDRESS = "0x" + "11" * 20
DEPENDENCY = "0x" + "22" * 20


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bash").mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(ROOT / "bash/verify.sh", self.root / "bash/verify.sh")
        self.log = self.root / "calls.jsonl"
        # Each external program is a controlled executable. No PATH fallback to real forge/cast.
        fake = f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
# Model Foundry's non-overriding dotenv autoload before Clap reads VERIFIER_URL.
if name == "forge":
    dotenv = pathlib.Path.cwd() / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)
with open(os.environ["CALL_LOG"], "a") as f:
    f.write(json.dumps({"tool": name, "args": sys.argv[1:],
                        "url": os.environ.get("VERIFIER_URL")}) + "\\n")
if name == "forge" and sys.argv[1:] == ["--version"]:
    print("forge Version: " + os.environ.get("FAKE_VERSION", "1.5.0-stable"))
elif name == "cast":
    print("0x1234")
else:
    sys.exit(int(os.environ.get("FAKE_VERIFY_EXIT", "0")))
'''
        for name in ("forge", "cast"):
            path = self.bin / name
            path.write_text(fake)
            path.chmod(0o755)
        self.fixture = ("NETWORK=mainnet\nETHERSCAN_API_KEY=public-test-key\n"
                        f"OWNER={ADDRESS}\nSMART_ACCOUNT={ADDRESS}\nUNDERLYING_TOKEN={ADDRESS}\n"
                        'VAULT_NAME="Public Fixture Vault"\nVAULT_SYMBOL=PFV\n'
                        f"DEPLOY_SALT=0x{'00' * 31}01\n")

    def run_verify(self, extra="", args=None, exported=None, root_env=None):
        (self.root / "bash/.env").write_text(self.fixture + extra)
        if root_env is not None:
            (self.root / ".env").write_text(root_env)
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root),
               "CALL_LOG": str(self.log)}
        env.update(exported or {})
        return self.execute(args, env)

    def execute(self, args, env):
        result = subprocess.run(["/bin/bash", str(self.root / "bash/verify.sh"),
                                 *(args or ["implementation", ADDRESS])],
                                cwd=self.root, env=env, text=True, capture_output=True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def test_rejects_old_forge_before_submission(self):
        result, calls = self.run_verify(exported={"FAKE_VERSION": "1.1.0-stable"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1.5.0", result.stdout + result.stderr)
        self.assertFalse(any(c["args"][0] == "verify-contract" for c in calls))


    def test_v2_defaults_survive_empty_exports_and_root_dotenv(self):
        for network, chain_id in (("mainnet", "1"), ("1", "1"), ("5042", "5042"),
                                  ("sepolia", "11155111"), ("8453", "8453")):
            with self.subTest(network=network):
                self.log.unlink(missing_ok=True)
                result, calls = self.run_verify(
                    extra=f"NETWORK={network}\nVERIFIER_URL=\n",
                    exported={"VERIFIER_URL": ""},
                    root_env="VERIFIER_URL=\nNETWORK=999\n")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                verify = next(c for c in calls if c["args"][0] == "verify-contract")
                expected = f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                self.assertIn("--verifier-url", verify["args"])
                self.assertEqual(verify["args"][verify["args"].index("--verifier-url") + 1], expected)
                self.assertEqual(verify["url"], expected)
                self.assertEqual(verify["args"][verify["args"].index("--chain") + 1], network)

    def test_root_dotenv_fallback_with_blank_url(self):
        (self.root / ".env").write_text(self.fixture + "VERIFIER_URL=\n")
        result, calls = self.execute(None, {"PATH": f"{self.bin}:/usr/bin:/bin",
                                           "HOME": str(self.root), "CALL_LOG": str(self.log)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verify = next(c for c in calls if c["args"][0] == "verify-contract")
        self.assertEqual(verify["url"], "https://api.etherscan.io/v2/api?chainid=1")

    def test_custom_url_preserves_query(self):
        url = "https://explorer.example/api?chainid=123&custom=value"
        result, calls = self.run_verify(extra=f"NETWORK=custom-chain\nVERIFIER_URL='{url}'\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verify = next(c for c in calls if c["args"][0] == "verify-contract")
        self.assertEqual(verify["args"][verify["args"].index("--verifier-url") + 1], url)
        self.assertEqual(verify["url"], url)

    def test_unknown_chain_alias_requires_explicit_url(self):
        result, calls = self.run_verify(extra="NETWORK=custom-chain\nVERIFIER_URL=\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VERIFIER_URL", result.stdout + result.stderr)
        self.assertFalse(any(c["args"][0] == "verify-contract" for c in calls))


    def test_contract_targets_and_constructor_inputs(self):
        targets = {"implementation": "src/SmartAccountWrapper.sol:SmartAccountWrapper",
                   "beacon": "UpgradeableBeacon.sol:UpgradeableBeacon",
                   "wrapper": "BeaconProxy.sol:BeaconProxy",
                   "staging": "src/Staging.sol:Staging",
                   "coordinator": "script/utils/AtomicDeployment.sol:AtomicDeployment"}
        for kind, target in targets.items():
            with self.subTest(kind=kind):
                self.log.unlink(missing_ok=True)
                result, calls = self.run_verify(args=[kind, ADDRESS, DEPENDENCY])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                verify = next(c for c in calls if c["args"][0] == "verify-contract")
                self.assertTrue(verify["args"][2].endswith(target))
                self.assertIn("--watch", verify["args"])
                self.assertIn("v0.8.30+commit.73712a01", verify["args"])
                self.assertIn("public-test-key", verify["args"])
                casts = [c["args"] for c in calls if c["tool"] == "cast"]
                if kind == "implementation":
                    self.assertFalse(casts)
                    self.assertNotIn("--constructor-args", verify["args"])
                else:
                    self.assertEqual(verify["args"][verify["args"].index("--constructor-args") + 1], "0x1234")
                    if kind in ("beacon", "staging", "wrapper"):
                        self.assertIn(DEPENDENCY, casts[-1])
                    if kind == "wrapper":
                        self.assertEqual(casts[0], ["calldata", "initialize(address,address,address,string,string)",
                                                   ADDRESS, ADDRESS, ADDRESS, "Public Fixture Vault", "PFV"])
                    if kind == "coordinator":
                        self.assertIn("constructor((address,address,address,string,string,bytes32))", casts[0])

    def test_submission_failure_is_propagated(self):
        result, _ = self.run_verify(exported={"FAKE_VERIFY_EXIT": "7"})
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("Verification submitted", result.stdout)

    def test_missing_constructor_dependency_does_not_submit(self):
        result, calls = self.run_verify(args=["beacon", ADDRESS])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implementation address", result.stdout)
        self.assertFalse(any(c["args"][0] == "verify-contract" for c in calls))

    def test_version_policy(self):
        for version, accepted in (("1.4.4-stable", False), ("1.5.0-stable", True),
                                  ("1.8.5-stable", True), ("1.9.0-nightly", True),
                                  ("2.0.0-stable", True), ("unknown", False)):
            with self.subTest(version=version):
                self.log.unlink(missing_ok=True)
                result, calls = self.run_verify(exported={"FAKE_VERSION": version})
                self.assertEqual(result.returncode == 0, accepted)
                self.assertEqual(any(c["args"][0] == "verify-contract" for c in calls), accepted)


if __name__ == "__main__":
    unittest.main()
