#!/bin/bash
# =============================================================================
# Verify Contracts on Block Explorer
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
fi

NETWORK=${NETWORK:-}
ETHERSCAN_API_KEY=${ETHERSCAN_API_KEY:-}
VERIFIER_URL=${VERIFIER_URL:-}
COMPILER_VERSION=${COMPILER_VERSION:-v0.8.30+commit.73712a01}
CONTRACT_TYPE=${1:-}
CONTRACT_ADDRESS=${2:-}
CONSTRUCTOR_ADDRESS=${3:-}

require_value() {
    local name=$1
    local value=$2
    if [ -z "$value" ]; then
        echo "Error: $name is required for $CONTRACT_TYPE verification"
        exit 1
    fi
}

usage() {
    echo "Usage: $0 <contract_type> <address> [constructor_dependency]"
    echo ""
    echo "Contract types:"
    echo "  beacon         - UpgradeableBeacon (third argument: implementation address)"
    echo "  implementation - SmartAccountWrapper implementation"
    echo "  wrapper        - BeaconProxy (third argument: beacon address)"
    echo "  staging        - Staging contract (third argument: wrapper address)"
    echo "  coordinator    - AtomicDeployment coordinator"
    echo ""
    echo "Examples:"
    echo "  $0 beacon 0x... 0x...       # beacon, implementation"
    echo "  $0 implementation 0x..."
    echo "  $0 wrapper 0x... 0x...      # wrapper, beacon"
    echo "  $0 staging 0x... 0x... # staging address, wrapper address"
    echo "  $0 coordinator 0x..."
    exit 1
}

if [ -z "$CONTRACT_TYPE" ] || [ -z "$CONTRACT_ADDRESS" ]; then
    usage
fi

if [ -z "$NETWORK" ]; then
    echo "Error: NETWORK not set in .env"
    exit 1
fi


cd "$PROJECT_ROOT"

if [ -z "$ETHERSCAN_API_KEY" ]; then
    echo "Error: ETHERSCAN_API_KEY is not set"
    exit 1
fi

# Foundry versions released before Arc Etherscan support do not know chain 5042's
# API URL. The matching [etherscan] entry in foundry.toml preserves the API key;
# this explicit URL also satisfies Foundry's custom-chain verifier guard.
if [ "$NETWORK" = "5042" ]; then
    VERIFIER_URL=${VERIFIER_URL:-https://api.etherscan.io/v2/api?chainid=5042}
fi

# foundry.toml resolves the Arc explorer key through this environment variable.
export ETHERSCAN_API_KEY

VERIFY_ARGS=(
    --chain "$NETWORK"
    --compiler-version "$COMPILER_VERSION"
    --verifier etherscan
    --etherscan-api-key "$ETHERSCAN_API_KEY"
    --watch
)
if [ -n "$VERIFIER_URL" ]; then
    VERIFY_ARGS+=(--verifier-url "$VERIFIER_URL")
fi

echo "=========================================="
echo "Verifying Contract"
echo "=========================================="
echo "Network:  $NETWORK"
echo "Type:     $CONTRACT_TYPE"
echo "Address:  $CONTRACT_ADDRESS"
echo "=========================================="
echo ""

case $CONTRACT_TYPE in
    beacon)
        echo "Verifying UpgradeableBeacon..."
        BEACON_IMPLEMENTATION=${CONSTRUCTOR_ADDRESS:-${IMPLEMENTATION_ADDRESS:-}}
        require_value "implementation address (third argument or IMPLEMENTATION_ADDRESS)" "$BEACON_IMPLEMENTATION"
        require_value "OWNER" "${OWNER:-}"
        CONSTRUCTOR_ARGS=$(cast abi-encode "constructor(address,address)" "$BEACON_IMPLEMENTATION" "$OWNER")
        forge verify-contract "$CONTRACT_ADDRESS" \
            lib/openzeppelin-contracts-upgradeable/lib/openzeppelin-contracts/contracts/proxy/beacon/UpgradeableBeacon.sol:UpgradeableBeacon \
            --constructor-args "$CONSTRUCTOR_ARGS" \
            "${VERIFY_ARGS[@]}"
        ;;

    implementation)
        echo "Verifying SmartAccountWrapper implementation..."
        forge verify-contract "$CONTRACT_ADDRESS" \
            src/SmartAccountWrapper.sol:SmartAccountWrapper \
            "${VERIFY_ARGS[@]}"
        ;;

    wrapper)
        echo "Verifying BeaconProxy (wrapper)..."
        BEACON_CONSTRUCTOR_ADDRESS=${CONSTRUCTOR_ADDRESS:-${BEACON_ADDRESS:-}}
        require_value "beacon address (third argument or BEACON_ADDRESS)" "$BEACON_CONSTRUCTOR_ADDRESS"
        require_value "OWNER" "${OWNER:-}"
        require_value "SMART_ACCOUNT" "${SMART_ACCOUNT:-}"
        require_value "UNDERLYING_TOKEN" "${UNDERLYING_TOKEN:-}"
        require_value "VAULT_NAME" "${VAULT_NAME:-}"
        require_value "VAULT_SYMBOL" "${VAULT_SYMBOL:-}"
        INITIALIZER_DATA=$(cast calldata "initialize(address,address,address,string,string)" \
            "$OWNER" "$SMART_ACCOUNT" "$UNDERLYING_TOKEN" "$VAULT_NAME" "$VAULT_SYMBOL")
        CONSTRUCTOR_ARGS=$(cast abi-encode "constructor(address,bytes)" \
            "$BEACON_CONSTRUCTOR_ADDRESS" "$INITIALIZER_DATA")
        forge verify-contract "$CONTRACT_ADDRESS" \
            lib/openzeppelin-contracts-upgradeable/lib/openzeppelin-contracts/contracts/proxy/beacon/BeaconProxy.sol:BeaconProxy \
            --constructor-args "$CONSTRUCTOR_ARGS" \
            "${VERIFY_ARGS[@]}"
        ;;

    staging)
        STAGING_VAULT=${CONSTRUCTOR_ADDRESS:-${WRAPPER_ADDRESS:-}}
        if [ -z "$STAGING_VAULT" ]; then
            echo "Error: staging verification requires the wrapper address as the third argument or WRAPPER_ADDRESS"
            usage
        fi
        echo "Verifying Staging..."
        CONSTRUCTOR_ARGS=$(cast abi-encode "constructor(address)" "$STAGING_VAULT")
        forge verify-contract "$CONTRACT_ADDRESS" \
            src/Staging.sol:Staging \
            --constructor-args "$CONSTRUCTOR_ARGS" \
            "${VERIFY_ARGS[@]}"
        ;;

    coordinator)
        require_value "OWNER" "${OWNER:-}"
        require_value "SMART_ACCOUNT" "${SMART_ACCOUNT:-}"
        require_value "UNDERLYING_TOKEN" "${UNDERLYING_TOKEN:-}"
        require_value "VAULT_NAME" "${VAULT_NAME:-}"
        require_value "VAULT_SYMBOL" "${VAULT_SYMBOL:-}"
        require_value "DEPLOY_SALT" "${DEPLOY_SALT:-}"
        echo "Verifying AtomicDeployment coordinator..."
        CONSTRUCTOR_ARGS=$(cast abi-encode "constructor((address,address,address,string,string,bytes32))" \
            "($OWNER,$SMART_ACCOUNT,$UNDERLYING_TOKEN,$VAULT_NAME,$VAULT_SYMBOL,$DEPLOY_SALT)")
        forge verify-contract "$CONTRACT_ADDRESS" \
            script/utils/AtomicDeployment.sol:AtomicDeployment \
            --constructor-args "$CONSTRUCTOR_ARGS" \
            "${VERIFY_ARGS[@]}"
        ;;

    *)
        echo "Error: Unknown contract type '$CONTRACT_TYPE'"
        usage
        ;;
esac

echo ""
echo "Verification submitted. Check block explorer for status."
