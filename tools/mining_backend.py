"""Local CPU/CUDA discovery and cached builds; no host access or RPC."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def cpu_binary(root, command):
    manifest = root / "tools/salt-miner/Cargo.toml"
    command(["cargo", "build", "--release", "--locked", "--offline", "--manifest-path", str(manifest)])
    metadata = json.loads(command(["cargo", "metadata", "--no-deps", "--locked", "--offline",
                                   "--format-version", "1", "--manifest-path", str(manifest)]))
    name = "k3-salt-miner.exe" if os.name == "nt" else "k3-salt-miner"
    return Path(metadata["target_directory"]) / "release" / name


def probe(binary):
    try:
        run = subprocess.run([str(binary), "--probe"], capture_output=True, text=True, timeout=15)
        if run.returncode:
            return None
        device = json.loads(run.stdout)
        if not isinstance(device, dict) or not isinstance(device.get("name"), str):
            return None
        if type(device.get("major")) is not int or type(device.get("minor")) is not int:
            return None
        return device
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def cuda_binary(root):
    compiler = shutil.which("nvcc")
    if not compiler:
        candidate = Path("/usr/local/cuda/bin/nvcc")
        if candidate.is_file() and os.access(candidate, os.X_OK):
            compiler = str(candidate)
    if not compiler:
        return None
    source = root / "tools/salt-miner/cuda/miner.cu"
    flags = ["-O3", "-std=c++17", "-arch=native"]
    temporary = None
    try:
        version = subprocess.run([compiler, "--version"], capture_output=True, timeout=15)
        if version.returncode:
            return None
        fingerprint = hashlib.sha256(source.read_bytes() + version.stdout + str(Path(compiler).resolve()).encode()
                                     + json.dumps(flags).encode()).hexdigest()
        cache = root / "tools/salt-miner/target/cuda"
        binary = cache / ("k3-salt-cuda.exe" if os.name == "nt" else "k3-salt-cuda")
        stamp = cache / "build.json"
        if binary.is_file() and stamp.is_file():
            try:
                saved = json.loads(stamp.read_text())
                if not isinstance(saved, dict):
                    saved = {}
            except (ValueError, OSError):
                saved = {}
            if saved.get("fingerprint") == fingerprint:
                device = probe(binary)
                if device and (device["major"], device["minor"]) == (saved.get("major"), saved.get("minor")):
                    return binary
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".exe" if os.name == "nt" else "", delete=False) as file:
            temporary = Path(file.name)
        print("Building CUDA miner for the local GPU...", file=sys.stderr)
        built = subprocess.run([compiler, *flags, str(source), "-o", str(temporary)],
                               capture_output=True, text=True, timeout=180)
        if built.returncode:
            return None
        device = probe(temporary)
        if not device:
            return None
        temporary.replace(binary)
        temporary = None
        stamp.write_text(json.dumps(dict(fingerprint=fingerprint, major=device["major"], minor=device["minor"])))
        return binary
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_backend(mode, root, command):
    if mode != "cpu":
        binary = cuda_binary(root)
        if binary:
            return "cuda", binary
        if mode == "cuda":
            raise ValueError("CUDA unavailable: a usable GPU and nvcc toolkit are required")
        print("CUDA unavailable or build/probe failed; falling back to CPU.", file=sys.stderr)
    return "cpu", cpu_binary(root, command)
