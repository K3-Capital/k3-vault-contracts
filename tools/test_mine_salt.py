#!/usr/bin/env python3
"""Offline integration tests for the deployment salt miner."""
import json
import contextlib
import io
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools import mine_salt
from tools.mine_salt import read_config

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/mine_salt.py"


def cast(*args):
    return subprocess.check_output(["cast", *args], cwd=ROOT, text=True).strip()


def keccak(data):
    return bytes.fromhex(cast("keccak", "0x" + data.hex())[2:])


def reference_addresses(salt, params):
    """Independent, unoptimized reference using Foundry's hash and ABI tools."""
    config = json.loads(subprocess.check_output(["forge", "config", "--json"], cwd=ROOT, text=True))
    artifact = json.loads((ROOT / config["out"] / "AtomicDeployment.sol/AtomicDeployment.json").read_text())
    code = bytes.fromhex(artifact["bytecode"]["object"].removeprefix("0x"))
    constructor = cast("abi-encode", "constructor((address,address,address,string,string,bytes32))",
                       f"({params['OWNER']},{params['SMART_ACCOUNT']},{params['UNDERLYING_TOKEN']},"
                       f"{params['VAULT_NAME']},{params['VAULT_SYMBOL']},0x{salt.hex()})")
    factory = bytes.fromhex(config["create2_deployer"][2:])
    coordinator = keccak(b"\xff" + factory + keccak(salt + b"atomic-deployment")
                         + keccak(code + bytes.fromhex(constructor[2:])))[12:]
    result = {"coordinator": "0x" + coordinator.hex()}
    proxy_hash = bytes.fromhex("21c35dbe1b344a2488cf3321d6ce542f8e9f305544ff09e4993a62319a497c1f")
    for label in ["implementation", "beacon", "wrapper"]:
        proxy = keccak(b"\xff" + coordinator + keccak(salt + label.encode()) + proxy_hash)[12:]
        result[label] = "0x" + keccak(b"\xd6\x94" + proxy + b"\x01")[12:].hex()
    return result


class MinerTest(unittest.TestCase):
    def setUp(self):
        self.params = {"OWNER": "0x" + "11" * 20, "SMART_ACCOUNT": "0x" + "22" * 20,
                       "UNDERLYING_TOKEN": "0x" + "44" * 20, "VAULT_NAME": "Test Vault",
                       "VAULT_SYMBOL": "TEST"}
        self.salt = (1).to_bytes(32, "big")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = Path(self.directory.name) / ".env"
        self.env.write_text("\n".join(f'{key}="{value}"' for key, value in self.params.items())
                            + "\nDEPLOY_SALT=0x" + self.salt.hex()
                            + "\nRPC_URL=https://SECRET-DO-NOT-PRINT.invalid\nETHERSCAN_API_KEY=SECRET-DO-NOT-PRINT\n")

    def invoke(self, *args):
        return subprocess.run(["python3", str(SCRIPT), "--env", str(self.env), *args],
                              cwd=ROOT, text=True, capture_output=True)

    def test_predict_matches_foundry_reference_without_exposing_secrets(self):
        self.assertTrue(SCRIPT.is_file(), "offline miner has not been implemented")
        params = {"OWNER": "0x" + "11" * 20, "SMART_ACCOUNT": "0x" + "22" * 20,
                  "UNDERLYING_TOKEN": "0x" + "44" * 20, "VAULT_NAME": "Test Vault",
                  "VAULT_SYMBOL": "TEST"}
        salt = (1).to_bytes(32, "big")
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("\n".join(f'{key}="{value}"' for key, value in params.items())
                           + "\nDEPLOY_SALT=0x" + salt.hex()
                           + "\nRPC_URL=https://SECRET-DO-NOT-PRINT.invalid\nETHERSCAN_API_KEY=SECRET-DO-NOT-PRINT\n")
            run = subprocess.run(["python3", str(SCRIPT), "--env", str(env), "--predict"],
                                 cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn("SECRET-DO-NOT-PRINT", run.stdout + run.stderr)
            result = json.loads(run.stdout)
            self.assertEqual(result["salt"], "0x" + salt.hex())
            self.assertEqual(result["addresses"], reference_addresses(salt, params))
            self.assertIn("initcodeHash", result)
            self.assertIn("create2Deployer", result)

    def test_prediction_matches_real_deployall_script(self):
        predicted = self.invoke("--predict")
        self.assertEqual(predicted.returncode, 0, predicted.stderr)
        addresses = json.loads(predicted.stdout)["addresses"]
        environment = os.environ.copy()
        environment.update(self.params)
        environment.update(DEPLOY_SALT="0x" + self.salt.hex(),
                           DEPLOYER_ADDRESS="0x" + "55" * 20)
        for key in ["ETH_RPC_URL", "FOUNDRY_ETH_RPC_URL", "DAPP_RPC_URL", "FOUNDRY_FORK_URL"]:
            environment.pop(key, None)
        effective = json.loads(subprocess.check_output(["forge", "config", "--json"],
                                                       cwd=ROOT, env=environment, text=True))
        self.assertFalse(effective.get("eth_rpc_url"), "local simulation must have no RPC configured")
        # No RPC or --broadcast: executes the actual deployment script locally.
        script = subprocess.run(["forge", "script", "script/Deploy.s.sol:DeployAll",
                                 "--offline", "--sender", environment["DEPLOYER_ADDRESS"]], cwd=ROOT,
                                env=environment, text=True, capture_output=True)
        self.assertEqual(script.returncode, 0, "local Foundry deployment simulation failed")
        for label, address in addresses.items():
            logged = re.search(rf"{label.capitalize()}:\s*(0x[0-9a-fA-F]{{40}})", script.stdout)
            self.assertIsNotNone(logged, f"missing {label} in simulation")
            assert logged is not None
            self.assertEqual(logged[1].lower(), address)

    def test_search_preserves_env_and_finds_odd_length_prefix(self):
        before = self.env.read_bytes()
        prefix = reference_addresses(self.salt, self.params)["wrapper"][2:5]
        run = self.invoke("--prefix", "0x" + prefix.upper(), "--max-attempts", "1")
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["salt"], "0x" + self.salt.hex())
        self.assertEqual(result["attempts"], 1)
        self.assertTrue(result["addresses"]["wrapper"].startswith("0x" + prefix))
        self.assertEqual(self.env.read_bytes(), before)

    def test_search_exhaustion_provides_next_salt(self):
        address = reference_addresses(self.salt, self.params)["wrapper"]
        prefix = "0" if address[2] != "0" else "1"
        run = self.invoke("--prefix", prefix, "--max-attempts", "1")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stdout, "")
        self.assertIn("--start 0x" + (2).to_bytes(32, "big").hex(), run.stderr)

    def test_multi_candidate_search_matches_reference(self):
        run = self.invoke("--prefix", "333", "--max-attempts", "1000000")
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertGreater(result["attempts"], 1)
        salt = bytes.fromhex(result["salt"][2:])
        self.assertEqual(int.from_bytes(salt, "big"), result["attempts"])
        self.assertTrue(result["addresses"]["wrapper"].startswith("0x333"))
        self.assertEqual(result["addresses"], reference_addresses(salt, self.params))

    def test_different_start_uses_different_constructor_salt(self):
        start = "0x" + (256).to_bytes(32, "big").hex()
        run = self.invoke("--predict", "--start", start)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["addresses"], reference_addresses(bytes.fromhex(start[2:]), self.params))

    def test_placeholder_rejected_without_secret_output(self):
        self.env.write_text(self.env.read_text().replace(self.params["SMART_ACCOUNT"], "0xYourSmartAccountAddress"))
        run = self.invoke("--predict")
        self.assertEqual(run.returncode, 1)
        self.assertIn("SMART_ACCOUNT", run.stderr)
        self.assertNotIn("SECRET-DO-NOT-PRINT", run.stdout + run.stderr)

    def test_invalid_prefix_and_salt_rejected(self):
        for args in [("--prefix", "0xxyz"), ("--start", "0x1"), ("--max-attempts", "0")]:
            with self.subTest(args=args):
                run = self.invoke(*args)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(run.stdout, "")

    def test_embedded_hash_matches_bash_literal(self):
        self.env.write_text(self.env.read_text().replace('VAULT_NAME="Test Vault"', 'VAULT_NAME=Vault#1 # trailing comment'))
        values = read_config(self.env)
        self.assertEqual(values["VAULT_NAME"], "Vault#1")

    def test_shell_separators_and_tilde_in_names_and_symbols_fail_closed(self):
        original = self.env.read_text()
        for key in ["VAULT_NAME", "VAULT_SYMBOL"]:
            for value in ["Vault;true", "Vault&true", "Vault|true", "Vault<input", "Vault>output", "~"]:
                for quote in ["", "'", '"']:
                    with self.subTest(key=key, value=value, quote=quote):
                        self.env.write_text(original.replace(
                            f'{key}="{self.params[key]}"', f"{key}={quote}{value}{quote}"))
                        with self.assertRaises(ValueError):
                            read_config(self.env)

    def test_name_and_symbol_boundary_whitespace_fail_closed(self):
        original = self.env.read_text()
        for key in ["VAULT_NAME", "VAULT_SYMBOL"]:
            for value in [" " + self.params[key], self.params[key] + " ",
                          " " + self.params[key] + " ",
                          "\t" + self.params[key], self.params[key] + "\t"]:
                for quote in ["'", '"']:
                    with self.subTest(key=key, value=value, quote=quote):
                        self.env.write_text(original.replace(
                            f'{key}="{self.params[key]}"', f"{key}={quote}{value}{quote}"))
                        with self.assertRaisesRegex(ValueError, f"{key}.*leading or trailing whitespace"):
                            read_config(self.env)

    def test_constructor_metadata_requires_exact_abi_string_fidelity(self):
        original = self.env.read_text()
        for key in ["VAULT_NAME", "VAULT_SYMBOL"]:
            with self.subTest(key=key):
                self.env.write_text(original.replace(
                    f'{key}="{self.params[key]}"', f'{key}="\'Vault\'"'))
                values = read_config(self.env)
                self.assertEqual(values[key], "'Vault'")
                with self.assertRaisesRegex(ValueError, key):
                    mine_salt.prepare(values)
        for name, symbol in [("Test Vault", "TEST"), ("Valentin's Vault", "V'S")]:
            with self.subTest(name=name, symbol=symbol):
                values = dict(self.params, VAULT_NAME=name, VAULT_SYMBOL=symbol,
                              DEPLOY_SALT="0x" + self.salt.hex())
                mine_salt.prepare(values)

    def test_selected_dotenv_foundry_overrides_fail_closed(self):
        original = self.env.read_text()
        for key, value in [("FOUNDRY_CREATE2_DEPLOYER", "0x" + "66" * 20),
                           ("FOUNDRY_PROFILE", "default")]:
            with self.subTest(key=key):
                self.env.write_text(original + f"\nexport {key}={value}\n")
                with self.assertRaisesRegex(ValueError, "unsupported tool override"):
                    read_config(self.env)

    def test_build_tools_are_explicitly_offline(self):
        with patch("tools.mine_salt.command", wraps=mine_salt.command) as commands, \
             patch("sys.argv", [str(SCRIPT), "--env", str(self.env), "--predict"]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mine_salt.main(), 0)
        calls = [call.args[0] for call in commands.call_args_list]
        self.assertIn(["forge", "build", "--offline"], calls)
        for call in calls:
            if call[0] == "cargo":
                self.assertIn("--offline", call)
                self.assertIn("--locked", call)

    def test_inherited_alternate_output_and_factory_match_reference(self):
        output = Path(self.directory.name) / "alternate-out"
        with patch.dict(os.environ, {"FOUNDRY_OUT": str(output),
                                     "FOUNDRY_CREATE2_DEPLOYER": "0x" + "77" * 20}):
            run = self.invoke("--predict")
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertTrue((output / "AtomicDeployment.sol/AtomicDeployment.json").is_file())
            self.assertEqual(result["create2Deployer"], "0x" + "77" * 20)
            self.assertEqual(result["addresses"], reference_addresses(self.salt, self.params))

    def test_export_job_contains_only_public_mining_input(self):
        job_file = Path(self.directory.name) / "mining-job.json"
        before = self.env.read_bytes()
        run = self.invoke("--prefix", "333333", "--max-attempts", "100", "--export-job", str(job_file))
        self.assertEqual(run.returncode, 0, run.stderr)
        job = json.loads(job_file.read_text())
        self.assertEqual(job["schemaVersion"], 1)
        self.assertEqual(job["parameters"], self.params)
        lines = job["input"].splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[3:], [self.salt.hex(), "333333", "100", "wrapper"])
        self.assertNotIn("SECRET-DO-NOT-PRINT", job_file.read_text() + run.stdout + run.stderr)
        self.assertEqual(self.env.read_bytes(), before)

    def test_remote_result_is_recomputed_on_cpu(self):
        prediction = self.invoke("--predict")
        self.assertEqual(prediction.returncode, 0, prediction.stderr)
        result = json.loads(prediction.stdout)
        prefix = result["addresses"]["wrapper"][2:5]
        result.update(prefix=prefix, searchStart="0x" + self.salt.hex(), searchLimit=1)
        result_file = Path(self.directory.name) / "gpu-result.json"
        result_file.write_text(json.dumps(result))
        verified = self.invoke("--prefix", prefix, "--verify-result", str(result_file))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["verification"], "cpu-confirmed")
        result["addresses"]["wrapper"] = "0x" + "00" * 20
        result_file.write_text(json.dumps(result))
        rejected = self.invoke("--prefix", prefix, "--verify-result", str(result_file))
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("CPU verification", rejected.stderr)

    def test_public_job_runner_roundtrip_with_native_protocol(self):
        runner = ROOT / "tools/run_gpu_job.py"
        self.assertTrue(runner.is_file(), "public GPU job runner has not been implemented")
        prediction = self.invoke("--predict")
        self.assertEqual(prediction.returncode, 0, prediction.stderr)
        prefix = json.loads(prediction.stdout)["addresses"]["wrapper"][2:5]
        job_file = Path(self.directory.name) / "job.json"
        exported = self.invoke("--prefix", prefix, "--max-attempts", "1", "--export-job", str(job_file))
        self.assertEqual(exported.returncode, 0, exported.stderr)
        metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--no-deps", "--offline", "--locked",
                                                       "--format-version", "1", "--manifest-path",
                                                       str(ROOT / "tools/salt-miner/Cargo.toml")], text=True))
        binary = Path(metadata["target_directory"]) / "release/k3-salt-miner"
        run = subprocess.run(["python3", str(runner), "--binary", str(binary), str(job_file)],
                             text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        result_file = Path(self.directory.name) / "result.json"
        result_file.write_text(run.stdout)
        result = json.loads(run.stdout)
        self.assertEqual(result["parameters"], self.params)
        self.assertEqual(result["prefix"], prefix)
        self.assertNotIn("SECRET-DO-NOT-PRINT", run.stdout + run.stderr)
        verified = self.invoke("--prefix", prefix, "--verify-result", str(result_file))
        self.assertEqual(verified.returncode, 0, verified.stderr)


    def test_auto_backend_one_command_preserves_configuration(self):
        prefix = reference_addresses(self.salt, self.params)["wrapper"][2:5]
        before = self.env.read_bytes()
        run = self.invoke("--backend", "auto", "--prefix", prefix, "--max-attempts", "1")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Backend:", run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["addresses"], reference_addresses(self.salt, self.params))
        self.assertEqual(self.env.read_bytes(), before)

    def test_cuda_checks_accept_host_local_binary_and_public_vectors(self):
        prediction = self.invoke("--predict")
        self.assertEqual(prediction.returncode, 0, prediction.stderr)
        expected = json.loads(prediction.stdout)
        expected.pop("parameters")
        factory, before, after = mine_salt.prepare(dict(self.params, DEPLOY_SALT="0x" + self.salt.hex()))
        payload = "\n".join([factory[2:], before.hex(), after.hex(), self.salt.hex(), "", "1", "wrapper"]) + "\n"
        vectors = Path(self.directory.name) / "vectors.json"
        vectors.write_text(json.dumps({"schemaVersion": 1, "cases": [
            {"name": "prediction", "input": payload, "exitCode": 0, "result": expected}]}))
        metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--no-deps", "--offline", "--locked",
                                                       "--format-version", "1", "--manifest-path",
                                                       str(ROOT / "tools/salt-miner/Cargo.toml")], text=True))
        binary = Path(metadata["target_directory"]) / "release/k3-salt-miner"
        run = subprocess.run(["python3", str(ROOT / "tools/salt-miner/cuda/test_cuda.py"),
                              "--binary", str(binary), "--vectors", str(vectors)], text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("1 CUDA protocol vectors passed", run.stdout)

    def test_auto_retries_cpu_if_cuda_binary_cannot_launch(self):
        prefix = reference_addresses(self.salt, self.params)["wrapper"][2:5]
        native = mine_salt.backends.cpu_binary(ROOT, mine_salt.command)
        unavailable = Path(self.directory.name) / "missing-cuda-binary"
        def select(mode, root, command):
            return ("cpu", native) if mode == "cpu" else ("cuda", unavailable)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(mine_salt.backends, "select_backend", side_effect=select), \
             patch("sys.argv", [str(SCRIPT), "--env", str(self.env), "--prefix", prefix, "--max-attempts", "1"]), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(mine_salt.main(), 0)
        self.assertIn("retrying the original search range", errors.getvalue())
        self.assertEqual(json.loads(output.getvalue())["addresses"], reference_addresses(self.salt, self.params))


    def test_cuda_protocol_winner_is_automatically_cpu_verified(self):
        # Backend-selection fixture: use the real native protocol to exercise
        # the complete GPU-result verification path without GPU hardware.
        prefix = reference_addresses(self.salt, self.params)["wrapper"][2:5]
        native = mine_salt.backends.cpu_binary(ROOT, mine_salt.command)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(mine_salt.backends, "select_backend", return_value=("cuda", native)), \
             patch("sys.argv", [str(SCRIPT), "--env", str(self.env), "--prefix", prefix, "--max-attempts", "1"]), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(mine_salt.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["verification"], "cpu-confirmed")

    def test_cuda_exhaustion_does_not_trigger_cpu_search(self):
        prefix = reference_addresses(self.salt, self.params)["wrapper"][2:5]
        fake = Path(self.directory.name) / "gpu-protocol-fixture"
        original_run = subprocess.run
        def run(args, **kwargs):
            if args == [str(fake)]:
                return subprocess.CompletedProcess(args, 2, stdout="", stderr="No match in 1 candidates.\n")
            return original_run(args, **kwargs)
        with patch.object(mine_salt.backends, "select_backend", return_value=("cuda", fake)) as select, \
             patch.object(mine_salt.subprocess, "run", side_effect=run), \
             patch("sys.argv", [str(SCRIPT), "--env", str(self.env), "--prefix", prefix, "--max-attempts", "1"]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mine_salt.main(), 2)
        select.assert_called_once()


if __name__ == "__main__":
    unittest.main()
