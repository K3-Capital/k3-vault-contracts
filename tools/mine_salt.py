#!/usr/bin/env python3
"""Mine a wrapper CREATE3 vanity address using the current DeployAll configuration.

Reads only public deployment parameters; does not source .env, use RPC, access a
wallet, modify configuration, or broadcast. CUDA is selected automatically when
usable, with a Rust CPU fallback and independent CPU verification of GPU winners.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

if __package__:
    from . import mining_backend as backends
else:
    import mining_backend as backends

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_KEYS = {"OWNER", "SMART_ACCOUNT", "UNDERLYING_TOKEN", "VAULT_NAME", "VAULT_SYMBOL", "DEPLOY_SALT"}
MANIFEST = ROOT / "tools/salt-miner/Cargo.toml"


def strip_comment(raw):
    """Bash starts a comment only at an unquoted token boundary."""
    quote = None
    escaped = False
    boundary = True
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            boundary = False
        elif char == "\\" and quote != "'":
            escaped = True
            boundary = False
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            boundary = False
        elif char == "#" and boundary:
            return raw[:index]
        else:
            boundary = char.isspace()
    return raw


def read_config(path):
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match and (match[1].startswith(("FOUNDRY_", "DAPP_", "CARGO_", "RUSTUP_"))
                      or match[1] in {"RUSTFLAGS", "SOLC_VERSION", "SOLC", "PATH"}):
            raise ValueError(f"{match[1]} is an unsupported tool override in the selected dotenv; "
                             "configure it in foundry.toml or the invoking shell instead")
        if not match or match[1] not in PUBLIC_KEYS:
            continue
        key, raw = match.groups()
        try:
            tokens = shlex.split(strip_comment(raw), comments=False)
        except ValueError:
            raise ValueError(f"Invalid quoting for {key} on line {number}") from None
        if len(tokens) != 1 or "$" in tokens[0] or "`" in tokens[0]:
            raise ValueError(f"{key} must be a literal value (quote names containing spaces)")
        if key in values:
            raise ValueError(f"Duplicate {key} in configuration")
        values[key] = tokens[0]
    for key in PUBLIC_KEYS:
        if not values.get(key):
            raise ValueError(f"Missing {key}")
    for key in ["OWNER", "SMART_ACCOUNT", "UNDERLYING_TOKEN"]:
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", values[key]) or int(values[key], 16) == 0:
            raise ValueError(f"{key} must be a nonzero 20-byte address; placeholders are not supported")
    validate_salt(values["DEPLOY_SALT"])
    # Shell syntax and cast's tuple delimiters can change values. Refuse ambiguous
    # values instead of silently mining addresses for different initialization data.
    for key in ["VAULT_NAME", "VAULT_SYMBOL"]:
        if values[key] != values[key].strip():
            raise ValueError(f"{key} must not contain leading or trailing whitespace")
        if any(char in values[key] for char in ',()"\\\n\r;&|<>~'):
            raise ValueError(f"{key} contains unsupported shell/tuple delimiters")
    return values


def validate_salt(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        raise ValueError("salt must be exactly 0x followed by 64 hex digits")
    return value


def command(args):
    # Never echo command diagnostics: inherited Foundry dotenv/RPC errors can
    # contain credentials. Successful output is consumed, not printed verbatim.
    run = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if run.returncode:
        hint = " Cache prerequisites with forge build and cargo fetch --locked --manifest-path tools/salt-miner/Cargo.toml." if "--offline" in args else ""
        raise ValueError(f"{args[0]} {args[1]} failed; run that tool separately to inspect diagnostics.{hint}")
    return run.stdout.strip()


def prepare(values):
    command(["forge", "build", "--offline"])
    config = json.loads(command(["forge", "config", "--json"]))
    factory = config["create2_deployer"]
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", factory):
        raise ValueError("Invalid Foundry CREATE2 deployer")
    artifact = json.loads((ROOT / config["out"] / "AtomicDeployment.sol/AtomicDeployment.json").read_text())
    code = bytes.fromhex(artifact["bytecode"]["object"].removeprefix("0x"))
    arguments = command(["cast", "abi-encode", "constructor((address,address,address,string,string,bytes32))",
                         f"({values['OWNER']},{values['SMART_ACCOUNT']},{values['UNDERLYING_TOKEN']},"
                         f"{values['VAULT_NAME']},{values['VAULT_SYMBOL']},{values['DEPLOY_SALT']})"])
    encoded = bytes.fromhex(arguments.removeprefix("0x"))
    # Dynamic tuple: first word is its offset; its sixth field is the salt.
    offset = 32 + 5 * 32
    if int.from_bytes(encoded[:32], "big") != 32 or encoded[offset:offset + 32].hex() != values['DEPLOY_SALT'][2:].lower():
        raise ValueError("Unexpected deployment constructor ABI layout")
    # Cast may normalize tuple strings; require the exact accepted UTF-8 bytes.
    for index, key in [(3, "VAULT_NAME"), (4, "VAULT_SYMBOL")]:
        head = 32 + index * 32
        payload = 32 + int.from_bytes(encoded[head:head + 32], "big")
        length = int.from_bytes(encoded[payload:payload + 32], "big")
        if encoded[payload + 32:payload + 32 + length] != values[key].encode("utf-8"):
            raise ValueError(f"{key} differs from its ABI-encoded value")
    return factory, code + encoded[:offset], encoded[offset + 32:]


def verify_candidate(result, factory, before, after, binary, prefix, start, limit):
    if not isinstance(result, dict):
        raise ValueError("GPU result failed CPU verification: invalid result")
    salt = validate_salt(result.get("salt", ""))
    ordinal = int(salt, 16) - int(start, 16) + 1
    if type(result.get("attempts")) is not int or not 1 <= ordinal <= limit or result["attempts"] != ordinal:
        raise ValueError("GPU result failed CPU verification: salt is outside its search range")
    check_input = "\n".join([factory[2:], before.hex(), after.hex(), salt[2:], "", "1", "wrapper"]) + "\n"
    check = subprocess.run([str(binary)], input=check_input, text=True, capture_output=True)
    if check.returncode:
        raise ValueError("GPU result failed CPU verification: prediction failed")
    predicted = json.loads(check.stdout)
    for key in ["addresses", "initcodeHash", "create2Deployer", "salt"]:
        if result.get(key) != predicted[key]:
            raise ValueError(f"GPU result failed CPU verification: {key} differs")
    if not predicted["addresses"]["wrapper"].startswith("0x" + prefix.lower()):
        raise ValueError("GPU result failed CPU verification: wrapper prefix does not match")
    result["verification"] = "cpu-confirmed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_env = ROOT / "bash/.env" if (ROOT / "bash/.env").exists() else ROOT / ".env"
    parser.add_argument("--env", type=Path, default=default_env, help="dotenv file (same precedence as deploy.sh)")
    parser.add_argument("--prefix", default="333333", help="wrapper hex prefix, optionally with 0x (default: 333333)")
    parser.add_argument("--start", help="first bytes32 salt to try (default: DEPLOY_SALT)")
    parser.add_argument("--max-attempts", type=int, default=100_000_000, help="bounded search limit; exhaustion exits 2")
    parser.add_argument("--backend", choices=["auto", "cpu", "cuda"], default="auto",
                        help="auto detects/builds CUDA and falls back to CPU (default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--predict", action="store_true", help="predict the starting salt without searching")
    mode.add_argument("--export-job", type=Path, help="write public GPU job JSON without searching (refuses overwrite)")
    mode.add_argument("--verify-result", type=Path, help="recompute a GPU result on CPU against current configuration")
    args = parser.parse_args()
    try:
        values = read_config(args.env)
        start = validate_salt(args.start) if args.start else values["DEPLOY_SALT"]
        prefix = args.prefix.removeprefix("0x")
        if not re.fullmatch(r"[0-9a-fA-F]{1,40}", prefix):
            raise ValueError("prefix must contain 1 to 40 hex digits")
        if not 0 < args.max_attempts < 2**64:
            raise ValueError("max-attempts must be between 1 and 2^64-1")
        if not args.predict and not args.verify_result and int(start, 16) + args.max_attempts > 2**256:
            raise ValueError("search range overflows bytes32")
        factory, before, after = prepare(values)
        payload = "\n".join([factory[2:], before.hex(), after.hex(), start[2:],
                             "" if args.predict else prefix.lower(),
                             "1" if args.predict else str(args.max_attempts), "wrapper"]) + "\n"
        if args.export_job:
            job = {"schemaVersion": 1, "input": payload,
                   "parameters": {key: values[key] for key in sorted(PUBLIC_KEYS - {"DEPLOY_SALT"})}}
            with args.export_job.open("x") as file:
                json.dump(job, file, indent=2)
                file.write("\n")
            print(json.dumps({"jobFile": str(args.export_job.resolve()), "prefix": prefix.lower(),
                              "parameters": job["parameters"]}, indent=2))
            return 0
        if args.verify_result:
            binary = backends.cpu_binary(ROOT, command)
            result = json.loads(args.verify_result.read_text())
            expected_params = {key: values[key] for key in sorted(PUBLIC_KEYS - {"DEPLOY_SALT"})}
            if not isinstance(result, dict) or result.get("parameters") != expected_params or result.get("prefix") != prefix.lower():
                raise ValueError("GPU result failed CPU verification: configuration or prefix differs")
            search_start = validate_salt(result.get("searchStart", ""))
            limit = result.get("searchLimit")
            if type(limit) is not int or not 0 < limit < 2**64:
                raise ValueError("GPU result failed CPU verification: invalid search limit")
            verify_candidate(result, factory, before, after, binary, prefix, search_start, limit)
            print(json.dumps(result, indent=2))
            return 0
        print("Offline prediction" if args.predict else f"Mining wrapper prefix 0x{prefix.lower()}; .env will not be changed", file=sys.stderr)
        for key in sorted(PUBLIC_KEYS - {"DEPLOY_SALT"}):
            print(f"  {key}={values[key]}", file=sys.stderr)
        mode = "cpu" if args.predict and args.backend == "auto" else args.backend
        selected, binary = backends.select_backend(mode, ROOT, command)
        print(f"Backend: {selected.upper()}", file=sys.stderr)
        try:
            run = subprocess.run([str(binary)], input=payload, text=True, capture_output=True)
        except OSError:
            if selected != "cuda" or args.backend != "auto":
                raise
            run = subprocess.CompletedProcess([str(binary)], 1, stdout="", stderr="Error: CUDA: unable to launch backend\n")
        if selected == "cuda" and args.backend == "auto" and run.returncode == 1 and "Error: CUDA:" in run.stderr:
            print("CUDA runtime failed; retrying the original search range on CPU.", file=sys.stderr)
            selected, binary = backends.select_backend("cpu", ROOT, command)
            print("Backend: CPU", file=sys.stderr)
            run = subprocess.run([str(binary)], input=payload, text=True, capture_output=True)
        print(run.stderr, end="", file=sys.stderr)
        if run.returncode:
            return run.returncode
        result = json.loads(run.stdout)
        if selected == "cuda":
            cpu = backends.cpu_binary(ROOT, command)
            verify_candidate(result, factory, before, after, cpu, "" if args.predict else prefix,
                             start, 1 if args.predict else args.max_attempts)
        result["parameters"] = {key: values[key] for key in sorted(PUBLIC_KEYS - {"DEPLOY_SALT"})}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
