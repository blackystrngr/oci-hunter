#!/usr/bin/env python3
"""
OCI Start – Continuous Retry (up to 6 hours)

Python/SDK rewrite of the original OCI-CLI/bash GitHub Actions script.
Repeatedly attempts to start an OCI compute instance until it reaches
RUNNING, or until a 6-hour ceiling is hit.

Install:
    pip install oci cryptography

Required environment variables (same names as the original workflow's secrets):
    OCI_USER_OCID
    OCI_FINGERPRINT
    OCI_TENANCY_OCID
    OCI_REGION
    OCI_PRIVATE_KEY     (PEM contents — CRLF or literal "\n" pasted keys are tolerated)
    OCI_INSTANCE_ID
"""

import os
import sys
import time
import logging
import urllib.request
import urllib.error

import oci
from oci.exceptions import ServiceError

# --------------------------------------------------------------------------
# Tunables (mirror the original bash script's constants)
# --------------------------------------------------------------------------

SIX_HOURS = 6 * 60 * 60      # overall ceiling, seconds
RETRY_DELAY = 10             # seconds between outer-loop attempts
STATE_CHECK_DELAY = 5        # seconds between state polls
START_WAIT_TIMEOUT = 300     # seconds to wait for RUNNING after issuing START
CONNECTION_TIMEOUT = 10      # seconds, per SDK call
READ_TIMEOUT = 30            # seconds, per SDK call

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oci-start")


# --------------------------------------------------------------------------
# Setup / credentials
# --------------------------------------------------------------------------

def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        log.error("❌ Required environment variable %s is empty/unset", name)
        sys.exit(1)
    return val


def build_key_file():
    """Write the private key (from env) to disk, fixing common paste issues:
    CRLF line endings and an accidentally single-line key with literal \\n."""
    raw_key = env("OCI_PRIVATE_KEY")
    key_path = os.path.expanduser("~/.oci/oci_api_private_key.pem")
    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    text = raw_key.replace("\r\n", "\n").replace("\r", "\n")
    if "BEGIN" not in text:
        log.error("❌ Private key doesn't look like a PEM file. Check OCI_PRIVATE_KEY formatting.")
        sys.exit(1)
    if text.count("\n") <= 1:
        text = text.replace("\\n", "\n")

    with open(key_path, "w") as f:
        f.write(text)
    os.chmod(key_path, 0o600)

    # Validate it's actually parseable before trusting it for hours of retries
    try:
        from cryptography.hazmat.primitives import serialization
        with open(key_path, "rb") as f:
            serialization.load_pem_private_key(f.read(), password=None)
    except Exception as e:
        log.error("❌ OCI_PRIVATE_KEY is not a valid/parseable PEM private key: %s", e)
        sys.exit(1)

    return key_path


def build_config():
    key_path = build_key_file()
    config = {
        "user": env("OCI_USER_OCID"),
        "fingerprint": env("OCI_FINGERPRINT"),
        "tenancy": env("OCI_TENANCY_OCID"),
        "region": env("OCI_REGION"),
        "key_file": key_path,
    }
    oci.config.validate_config(config)
    return config


def verify_auth(config):
    """Fail-fast auth check, equivalent to `oci iam region list`."""
    try:
        identity = oci.identity.IdentityClient(
            config,
            timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT),
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )
        identity.list_regions()
        log.info("✅ OCI credentials are valid.")
    except ServiceError as e:
        log.error("❌ Auth check failed (status %s): %s", e.status, e.message)
        log.error("This means your OCI credentials/config are wrong — retrying won't help.")
        sys.exit(1)


def check_network(region):
    """Reachability check, equivalent to the curl probe in the original script."""
    endpoint = f"https://iaas.{region}.oraclecloud.com/20160918/instances"
    log.info("Checking reachability of: %s", endpoint)
    try:
        urllib.request.urlopen(urllib.request.Request(endpoint), timeout=15)
    except urllib.error.HTTPError:
        pass  # any HTTP response (even 4xx) proves the connection isn't hanging
    except Exception as e:
        log.error("❌ Could not connect within 15s: %s", e)
        log.error("This is a runner-side network/DNS problem to Oracle's API, not credentials.")
        sys.exit(1)
    log.info("✅ Endpoint is reachable.")


# --------------------------------------------------------------------------
# Instance state machine
# --------------------------------------------------------------------------

def get_state(compute, instance_id):
    try:
        return compute.get_instance(instance_id).data.lifecycle_state
    except ServiceError as e:
        log.warning("⚠️ Couldn't read instance state: %s", e.message)
        return None


def wait_for_running(compute, instance_id, timeout):
    wait_start = time.monotonic()
    while True:
        if time.monotonic() - wait_start > timeout:
            log.info("⏰ Timeout waiting for RUNNING. Will retry.")
            return False
        state = get_state(compute, instance_id)
        log.info("   ➜ Current state: %s", state)
        if state == "RUNNING":
            log.info("✅ Instance reached RUNNING – success!")
            return True
        if state in ("STOPPED", "STOPPING"):
            log.info("   ⚠️ Instance went back to %s – start likely failed.", state)
            return False
        time.sleep(STATE_CHECK_DELAY)


def main():
    instance_id = env("OCI_INSTANCE_ID")
    log.info("✅ Instance ID: %s...", instance_id[:8])

    config = build_config()
    verify_auth(config)
    check_network(config["region"])

    compute = oci.core.ComputeClient(
        config,
        timeout=(CONNECTION_TIMEOUT, READ_TIMEOUT),
        retry_strategy=oci.retry.NoneRetryStrategy(),
    )

    start_epoch = time.monotonic()
    attempt = 0

    while True:
        elapsed = time.monotonic() - start_epoch
        if elapsed > SIX_HOURS:
            log.info("⏹️ 6-hour limit reached – exiting.")
            return 0

        attempt += 1
        log.info("--- Attempt #%d (%ds elapsed) ---", attempt, int(elapsed))

        state = get_state(compute, instance_id)
        log.info("📌 Instance state: %s", state)

        if state == "RUNNING":
            log.info("✅ Instance is already RUNNING – success!")
            return 0

        elif state == "STOPPED":
            log.info("🚀 Sending start command...")
            try:
                compute.instance_action(instance_id, action="START")
                log.info("✅ Start command accepted. Waiting for RUNNING...")
                if wait_for_running(compute, instance_id, START_WAIT_TIMEOUT):
                    return 0
            except ServiceError as e:
                log.error("❌ Start command failed (status %s): %s", e.status, e.message)

        elif state in ("STOPPING", "STARTING"):
            log.info("⏳ Instance is %s – waiting for it to settle.", state)
            time.sleep(STATE_CHECK_DELAY)
            continue

        else:
            log.warning("⚠️ Unhandled state: %s – waiting %ds.", state, RETRY_DELAY)

        log.info("⏳ Sleeping %ds before next attempt...", RETRY_DELAY)
        time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    sys.exit(main())
