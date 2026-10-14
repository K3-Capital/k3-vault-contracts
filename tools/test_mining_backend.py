"""Backend selection tests; do not require local GPU hardware."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BackendTest(unittest.TestCase):
    def test_auto_uses_cpu_when_cuda_is_unavailable(self):
        path = ROOT / "tools/mining_backend.py"
        self.assertTrue(path.is_file(), "automatic backend selection has not been implemented")
        from tools import mining_backend
        with patch.object(mining_backend, "cuda_binary", return_value=None) as cuda, \
             patch.object(mining_backend, "cpu_binary", return_value=Path("cpu")) as cpu:
            selected, binary = mining_backend.select_backend("auto", ROOT, lambda args: "")
        self.assertEqual((selected, binary), ("cpu", Path("cpu")))
        cuda.assert_called_once_with(ROOT)
        cpu.assert_called_once()

    def test_auto_prefers_cuda_without_building_cpu(self):
        from tools import mining_backend
        with patch.object(mining_backend, "cuda_binary", return_value=Path("gpu")), \
             patch.object(mining_backend, "cpu_binary") as cpu:
            self.assertEqual(mining_backend.select_backend("auto", ROOT, lambda args: ""),
                             ("cuda", Path("gpu")))
        cpu.assert_not_called()

    def test_forced_cpu_skips_cuda_detection(self):
        from tools import mining_backend
        with patch.object(mining_backend, "cuda_binary") as cuda, \
             patch.object(mining_backend, "cpu_binary", return_value=Path("cpu")):
            self.assertEqual(mining_backend.select_backend("cpu", ROOT, lambda args: ""),
                             ("cpu", Path("cpu")))
        cuda.assert_not_called()

    def test_forced_cuda_does_not_silently_fallback(self):
        from tools import mining_backend
        with patch.object(mining_backend, "cuda_binary", return_value=None), \
             patch.object(mining_backend, "cpu_binary") as cpu:
            with self.assertRaisesRegex(ValueError, "CUDA unavailable"):
                mining_backend.select_backend("cuda", ROOT, lambda args: "")
        cpu.assert_not_called()


    def test_cuda_build_cache_reuses_and_recovers_invalid_metadata(self):
        from tools import mining_backend
        builds = []
        def compiler(args, **kwargs):
            if "--version" in args:
                return subprocess.CompletedProcess(args, 0, stdout=b"test compiler", stderr=b"")
            builds.append(args)
            Path(args[args.index("-o") + 1]).write_bytes(b"unit-test executable fixture")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tools/salt-miner/cuda/miner.cu"
            source.parent.mkdir(parents=True)
            source.write_text("unit-test source")
            with patch.object(mining_backend.shutil, "which", return_value="/unit-test/nvcc"), \
                 patch.object(mining_backend.subprocess, "run", side_effect=compiler), \
                 patch.object(mining_backend, "probe", return_value={"name": "test GPU", "major": 8, "minor": 6}):
                binary = mining_backend.cuda_binary(root)
                self.assertIsNotNone(binary)
                self.assertEqual(mining_backend.cuda_binary(root), binary)
                self.assertEqual(len(builds), 1)
                source.write_text("changed unit-test source")
                self.assertEqual(mining_backend.cuda_binary(root), binary)
                self.assertEqual(len(builds), 2)
                (root / "tools/salt-miner/target/cuda/build.json").write_text("invalid JSON")
                self.assertEqual(mining_backend.cuda_binary(root), binary)
                self.assertEqual(len(builds), 3)


if __name__ == "__main__":
    unittest.main()
