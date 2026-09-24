#!/usr/bin/env python3
"""Regression tests for the deployment registry validator."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deployments import validate

from deployments.validate import (
    SMOKE_METHODS,
    resolve_local_path,
    validate_broadcast_integrity,
    validate_smoke_test,
    validate_transactions,
)

TEST_ACCOUNT = "0x1111111111111111111111111111111111111111"
SMART_ACCOUNT = "0x2222222222222222222222222222222222222222"
WRAPPER = "0x3333333333333333333333333333333333333333"
HASH_1 = "0x" + "11" * 32
HASH_2 = "0x" + "22" * 32


def smoke_transaction() -> dict[str, object]:
    return {
        "sequence": 1,
        "hash": HASH_1,
        "block": 1,
        "transactionIndex": 0,
        "timestamp": "2026-08-04T09:11:47Z",
        "status": 1,
        "sender": TEST_ACCOUNT,
        "method": "requestDeposit(uint256,address,address)",
        "arguments": {
            "assets": "1",
            "controller": TEST_ACCOUNT,
            "owner": TEST_ACCOUNT,
        },
        "gasUsed": 1,
    }


def smoke_document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "evidenceType": "mainnet-smoke-test",
        "network": {"name": "Test Network", "chainId": 1},
        "wrapper": WRAPPER,
        "actors": {"testAccount": TEST_ACCOUNT, "smartAccount": SMART_ACCOUNT},
        "units": {
            "assets": "asset base units",
            "shares": "share base units",
            "navSnapshot": "asset base units",
            "decimals": 8,
        },
        "status": "passed",
        "firstBlock": 1,
        "lastBlock": 1,
        "transactions": [smoke_transaction()],
    }


def smoke_manifest() -> dict[str, object]:
    return {
        "network": {"name": "Test Network", "chainId": 1},
        "vault": {"decimals": 8},
        "contracts": {"wrapperProxy": {"address": WRAPPER}},
        "verification": {
            "mainnetSmokeTest": {
                "status": "passed",
                "transactionCount": 1,
                "firstBlock": 1,
                "lastBlock": 1,
                "evidenceFile": "smoke-test.json",
                "evidenceSha256": "11" * 32,
                "operations": {"requestDeposit": 1},
                "transactionList": "https://example.invalid/transactions",
            }
        },
    }


class TransactionValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.actors = {
            "testAccount": TEST_ACCOUNT,
            "smartAccount": SMART_ACCOUNT,
        }

    def assert_invalid(self, field: str, value: object) -> None:
        transaction = smoke_transaction()
        transaction[field] = value
        with self.assertRaises(ValueError):
            validate_transactions([transaction], "test", self.actors)

    def test_valid_smoke_transaction(self) -> None:
        validate_transactions([smoke_transaction()], "test", self.actors)

    def test_boolean_integer_fields_are_rejected(self) -> None:
        for field in ("sequence", "block", "transactionIndex", "status", "gasUsed"):
            with self.subTest(field=field):
                self.assert_invalid(field, True)

    def test_invalid_sender_is_rejected(self) -> None:
        self.assert_invalid("sender", "not-an-address")

    def test_wrong_actor_is_rejected(self) -> None:
        self.assert_invalid("sender", SMART_ACCOUNT)

    def test_invalid_timestamp_is_rejected(self) -> None:
        self.assert_invalid("timestamp", "2026-08-04")

    def test_noncanonical_but_parseable_timestamp_is_rejected(self) -> None:
        self.assert_invalid("timestamp", "2026-8-4T9:1:7Z")

    def test_unknown_method_is_rejected(self) -> None:
        self.assert_invalid("method", "unknown()")

    def test_argument_schema_and_types_are_strict(self) -> None:
        missing = smoke_transaction()
        del missing["arguments"]["owner"]  # type: ignore[index]
        with self.assertRaises(ValueError):
            validate_transactions([missing], "test", self.actors)

        extra = smoke_transaction()
        extra["arguments"]["unexpected"] = "1"  # type: ignore[index]
        with self.assertRaises(ValueError):
            validate_transactions([extra], "test", self.actors)

        invalid_type = smoke_transaction()
        invalid_type["arguments"]["assets"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            validate_transactions([invalid_type], "test", self.actors)

        invalid_address = smoke_transaction()
        invalid_address["arguments"]["owner"] = "not-an-address"  # type: ignore[index]
        with self.assertRaises(ValueError):
            validate_transactions([invalid_address], "test", self.actors)

        overflowing_uint = smoke_transaction()
        overflowing_uint["arguments"]["assets"] = str(1 << 256)  # type: ignore[index]
        with self.assertRaises(ValueError):
            validate_transactions([overflowing_uint], "test", self.actors)

        overflowing_uint40 = smoke_transaction()
        overflowing_uint40["method"] = "settleEpoch(uint40,uint256)"
        overflowing_uint40["sender"] = SMART_ACCOUNT
        overflowing_uint40["arguments"] = {
            "epochId": str(1 << 40),
            "navSnapshot": "1",
        }
        with self.assertRaises(ValueError):
            validate_transactions([overflowing_uint40], "test", self.actors)

    def test_extra_transaction_field_is_rejected(self) -> None:
        transaction = smoke_transaction()
        transaction["unexpected"] = "field"
        with self.assertRaises(ValueError):
            validate_transactions([transaction], "test", self.actors)

    def test_nonpositive_gas_is_rejected(self) -> None:
        for gas_used in (0, -1):
            with self.subTest(gas_used=gas_used):
                self.assert_invalid("gasUsed", gas_used)

    def test_every_supported_method_and_sender_role_is_accepted(self) -> None:
        for method, (role, argument_schema) in SMOKE_METHODS.items():
            with self.subTest(method=method):
                transaction = smoke_transaction()
                transaction["method"] = method
                transaction["sender"] = self.actors[role]
                transaction["arguments"] = {
                    name: TEST_ACCOUNT if kind == "address" else "1"
                    for name, kind in argument_schema.items()
                }
                validate_transactions([transaction], "test", self.actors)

    def test_duplicate_position_and_reverse_timestamp_are_rejected(self) -> None:
        first = smoke_transaction()
        second = copy.deepcopy(first)
        second["sequence"] = 2
        second["hash"] = HASH_2
        with self.assertRaises(ValueError):
            validate_transactions([first, second], "test", self.actors)

        second["block"] = 2
        second["timestamp"] = "2026-08-04T09:11:46Z"
        with self.assertRaises(ValueError):
            validate_transactions([first, second], "test", self.actors)


class SmokeDocumentValidationTest(unittest.TestCase):
    def validate_document(
        self,
        document: dict[str, object] | None = None,
        manifest: dict[str, object] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smoke-test.json"
            path.write_text(json.dumps(document or smoke_document()), encoding="utf-8")
            validate_smoke_test(path, manifest or smoke_manifest())

    def test_valid_document(self) -> None:
        self.validate_document()

    def test_extra_envelope_and_network_fields_are_rejected(self) -> None:
        document = smoke_document()
        document["unexpected"] = "field"
        with self.assertRaises(ValueError):
            self.validate_document(document)

        document = smoke_document()
        document["network"]["unexpected"] = "field"  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(document)

    def test_extra_manifest_smoke_field_is_rejected(self) -> None:
        manifest = smoke_manifest()
        record = manifest["verification"]["mainnetSmokeTest"]  # type: ignore[index]
        record["unexpected"] = "field"  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(manifest=manifest)

    def test_status_chain_decimals_and_block_range_are_strict(self) -> None:
        document = smoke_document()
        document["status"] = "failed"
        with self.assertRaises(ValueError):
            self.validate_document(document)

        document = smoke_document()
        document["network"]["chainId"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(document)

        document = smoke_document()
        document["units"]["decimals"] = 18  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(document)

        document = smoke_document()
        document["lastBlock"] = 2
        with self.assertRaises(ValueError):
            self.validate_document(document)

    def test_manifest_counts_and_status_are_strict(self) -> None:
        manifest = smoke_manifest()
        record = manifest["verification"]["mainnetSmokeTest"]  # type: ignore[index]
        record["status"] = False  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(manifest=manifest)

        manifest = smoke_manifest()
        record = manifest["verification"]["mainnetSmokeTest"]  # type: ignore[index]
        record["transactionCount"] = 2  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(manifest=manifest)

        manifest = smoke_manifest()
        record = manifest["verification"]["mainnetSmokeTest"]  # type: ignore[index]
        record["operations"] = {"requestDeposit": 2}  # type: ignore[index]
        with self.assertRaises(ValueError):
            self.validate_document(manifest=manifest)


class BroadcastIntegrityTest(unittest.TestCase):
    def test_clean_future_artifact_is_accepted(self) -> None:
        validate_broadcast_integrity({"integrityStatus": "valid"}, {HASH_1}, "test")

    def test_known_anomaly_accepts_arbitrary_nonempty_mapping_list(self) -> None:
        broadcast = {
            "integrityStatus": "known-hash-to-payload-misassociations",
            "knownHashMisassociations": [
                {
                    "payload": "test payload",
                    "recordedHash": HASH_1,
                    "correctHash": HASH_2,
                }
            ],
        }
        validate_broadcast_integrity(broadcast, {HASH_1, HASH_2}, "test")

    def test_clean_artifact_cannot_declare_anomalies(self) -> None:
        broadcast = {
            "integrityStatus": "valid",
            "knownHashMisassociations": [copy.deepcopy({"payload": "invalid"})],
        }
        with self.assertRaises(ValueError):
            validate_broadcast_integrity(broadcast, {HASH_1}, "test")


class ManifestValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        original = validate.DEPLOYMENTS / "1/0x009c02a73706a68e0aE0209235408206E4F53709"
        self.directory = self.root / "deployments" / original.relative_to(validate.DEPLOYMENTS)
        shutil.copytree(original, self.directory)
        self.path = self.directory / "deployment.json"
        self.manifest = validate.load_json(self.path)
        broadcast = Path(self.manifest["source"]["foundryBroadcast"]["fileName"])
        (self.root / broadcast).parent.mkdir(parents=True)
        shutil.copyfile(validate.ROOT / broadcast, self.root / broadcast)
        shutil.copyfile(validate.DEPLOYMENTS / "README.md", self.root / "deployments/README.md")

    def validate_manifest(self) -> None:
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with patch.object(validate, "ROOT", self.root), patch.object(
            validate, "DEPLOYMENTS", self.root / "deployments"
        ):
            validate.validate_manifest(self.path)

    def test_eoa_settlement_account_does_not_require_delegation(self) -> None:
        account = copy.deepcopy(self.manifest["privilegedAccounts"]["owner"])
        account["address"] = self.manifest["configuration"]["smartAccount"]
        account["authorities"] = ["close epochs", "settle epochs"]
        self.manifest["privilegedAccounts"]["smartAccount"] = account
        self.manifest["verification"]["postSmokeState"]["smartAccountDelegationTarget"] = None
        self.validate_manifest()

    def mark_smoke_test_not_performed(self) -> None:
        self.manifest["status"] = "deployed-pending-activation"
        self.manifest["verification"]["mainnetSmokeTest"] = {
            "status": "not-performed",
            "reason": "Read-only verification; no funded end-to-end transactions submitted.",
        }
        del self.manifest["verification"]["postSmokeState"]
        del self.manifest["verification"]["postSmokeSnapshot"]
        self.manifest["documentation"]["smokeTestEvidence"] = None
        (self.directory / "smoke-test.json").unlink()

    def test_pending_deployment_does_not_require_fabricated_smoke_evidence(self) -> None:
        self.mark_smoke_test_not_performed()
        self.validate_manifest()

    def test_unperformed_smoke_cannot_claim_active_status(self) -> None:
        self.mark_smoke_test_not_performed()
        self.manifest["status"] = "active"
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_unperformed_smoke_requires_reason_and_no_success_fields(self) -> None:
        self.mark_smoke_test_not_performed()
        record = self.manifest["verification"]["mainnetSmokeTest"]
        for reason in ("", None, True):
            with self.subTest(reason=reason):
                record["reason"] = reason
                with self.assertRaises(ValueError):
                    self.validate_manifest()
        record["reason"] = "Not yet performed."
        record["transactionCount"] = 0
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_unperformed_smoke_cannot_reference_evidence(self) -> None:
        self.mark_smoke_test_not_performed()
        self.manifest["documentation"]["smokeTestEvidence"] = "smoke-test.json"
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_unperformed_smoke_cannot_claim_post_smoke_snapshot(self) -> None:
        self.mark_smoke_test_not_performed()
        for key in ("postSmokeSnapshot", "postSmokeState"):
            with self.subTest(key=key):
                self.manifest["verification"][key] = {}
                with self.assertRaises(ValueError):
                    self.validate_manifest()
                del self.manifest["verification"][key]

    def test_unknown_settlement_account_type_is_rejected(self) -> None:
        self.manifest["privilegedAccounts"]["smartAccount"]["accountType"] = "unknown"
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_eoa_cannot_claim_code_delegation_or_onchain_protection(self) -> None:
        account = copy.deepcopy(self.manifest["privilegedAccounts"]["owner"])
        account["address"] = self.manifest["configuration"]["smartAccount"]
        self.manifest["verification"]["postSmokeState"]["smartAccountDelegationTarget"] = None
        for key, value in (
            ("runtimeCode", "0xef0100" + "11" * 20),
            ("runtimeBytecodeKeccak256", HASH_1),
            ("onchainMultisigOrTimelock", True),
            ("onchainMultisigOrTimelock", 0),
            ("delegationTarget", {"address": SMART_ACCOUNT}),
        ):
            with self.subTest(key=key, value=value):
                self.manifest["privilegedAccounts"]["smartAccount"] = {**account, key: value}
                with self.assertRaises(ValueError):
                    self.validate_manifest()
        self.manifest["privilegedAccounts"]["smartAccount"] = account
        self.manifest["verification"]["postSmokeState"]["smartAccountDelegationTarget"] = SMART_ACCOUNT
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_passed_smoke_still_requires_evidence(self) -> None:
        (self.directory / "smoke-test.json").unlink()
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_passed_smoke_still_requires_delegation_cross_check(self) -> None:
        del self.manifest["verification"]["postSmokeState"]
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_explorer_status_evidence_hash_is_enforced(self) -> None:
        evidence_path = self.directory / "explorer-status.json"
        evidence_path.write_bytes(b"verified explorer status\n")
        self.manifest["verification"]["sourceVerification"]["evidence"] = {
            "fileName": evidence_path.name,
            "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        }
        self.validate_manifest()

        evidence_path.write_bytes(b"tampered\n")
        with self.assertRaises(ValueError):
            self.validate_manifest()

    def test_create3_record_requires_all_salts_and_deployers(self) -> None:
        create3 = self.manifest["deployment"]["create3"]
        for collection in ("derivedSalts", "ephemeralDeployers"):
            with self.subTest(collection=collection):
                value = create3[collection].pop("wrapper")
                with self.assertRaises(ValueError):
                    self.validate_manifest()
                create3[collection]["wrapper"] = value

        create3["derivedSalts"]["wrapper"] = WRAPPER
        with self.assertRaises(ValueError):
            self.validate_manifest()


class LocalPathValidationTest(unittest.TestCase):
    def test_valid_relative_path_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(resolve_local_path(root, "evidence.json", root, "evidence"), root / "evidence.json")

    def test_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                resolve_local_path(root, "../evidence.json", root, "evidence")

    def test_absolute_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                resolve_local_path(root, "/tmp/evidence.json", root, "evidence")

    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root_directory:
            with tempfile.TemporaryDirectory() as outside_directory:
                root = Path(root_directory)
                (root / "outside").symlink_to(outside_directory, target_is_directory=True)
                with self.assertRaises(ValueError):
                    resolve_local_path(root, "outside/evidence.json", root, "evidence")


if __name__ == "__main__":
    unittest.main()
