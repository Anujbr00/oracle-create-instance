#!/usr/bin/env python3
"""
Oracle Cloud Always Free ARM (A1.Flex) capacity catcher — single-attempt mode.
DIAGNOSTIC VERSION: adds unbuffered print statements at every stage and a
top-level catch-all so a silent failure becomes visible in the Actions log.
"""

import os
import sys
import traceback

print("=== catcher script starting ===", flush=True)

try:
    import logging
    import oci
    import requests
    print("=== imports OK ===", flush=True)
except Exception:
    print("=== IMPORT FAILED ===", flush=True)
    traceback.print_exc()
    sys.exit(1)

GITHUB_OUTPUT = os.getenv("GITHUB_OUTPUT")


def set_output(caught: bool) -> None:
    print(f"=== set_output(caught={caught}) called, GITHUB_OUTPUT={GITHUB_OUTPUT!r} ===", flush=True)
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"caught={'true' if caught else 'false'}\n")


try:
    COMPARTMENT_ID = os.environ["OCI_COMPARTMENT_ID"]
    SUBNET_ID = os.environ["OCI_SUBNET_ID"]
    OCI_ADS_RAW = os.environ["OCI_ADS"]
    AVAILABILITY_DOMAINS = [a.strip() for a in OCI_ADS_RAW.split(",") if a.strip()]
    IMAGE_ID = os.environ["OCI_IMAGE_ID"]
    SSH_PUBLIC_KEY = os.environ["SSH_PUBLIC_KEY"]
    SHAPE = os.getenv("OCI_SHAPE", "VM.Standard.A1.Flex")
    OCPUS = float(os.getenv("OCI_OCPUS", "1"))
    MEMORY_GB = float(os.getenv("OCI_MEMORY_GB", "6"))
    DISPLAY_NAME = os.getenv("OCI_DISPLAY_NAME", "openclaw-2")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    print(f"=== config loaded. ADs found: {AVAILABILITY_DOMAINS} (count={len(AVAILABILITY_DOMAINS)}) ===", flush=True)
    print(f"=== compartment={COMPARTMENT_ID[:20]}... subnet={SUBNET_ID[:20]}... image={IMAGE_ID[:20]}... ===", flush=True)
except Exception:
    print("=== CONFIG/ENV LOADING FAILED ===", flush=True)
    traceback.print_exc()
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("catcher")


def notify_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("=== Telegram not configured, skipping notify ===", flush=True)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        print(f"=== Telegram response: {r.status_code} ===", flush=True)
    except Exception as e:
        print(f"=== Telegram notify failed: {e} ===", flush=True)


def is_capacity_error(e) -> bool:
    if getattr(e, "code", None) == "OutOfHostCapacity":
        return True
    if getattr(e, "code", None) == "InternalError" and "Out of host capacity" in (getattr(e, "message", "") or ""):
        return True
    return False


def already_exists(compute_client) -> bool:
    print("=== checking for existing instance ===", flush=True)
    instances = compute_client.list_instances(
        compartment_id=COMPARTMENT_ID, display_name=DISPLAY_NAME
    ).data
    print(f"=== found {len(instances)} instance(s) with display_name={DISPLAY_NAME} ===", flush=True)
    return any(
        i.lifecycle_state in ("RUNNING", "PROVISIONING", "STARTING") for i in instances
    )


def try_launch(compute_client, ad: str):
    details = oci.core.models.LaunchInstanceDetails(
        compartment_id=COMPARTMENT_ID,
        availability_domain=ad,
        shape=SHAPE,
        display_name=DISPLAY_NAME,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS, memory_in_gbs=MEMORY_GB
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=SUBNET_ID, assign_public_ip=True
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=IMAGE_ID),
        metadata={"ssh_authorized_keys": SSH_PUBLIC_KEY},
    )
    return compute_client.launch_instance(details).data


def main():
    print("=== main() entered ===", flush=True)
    config = oci.config.from_file()
    print(f"=== OCI config loaded from file, region={config.get('region')} ===", flush=True)
    compute_client = oci.core.ComputeClient(config)
    print("=== compute client created ===", flush=True)

    if already_exists(compute_client):
        print("=== Instance already exists — nothing to do ===", flush=True)
        set_output(True)
        return

    if not AVAILABILITY_DOMAINS:
        print("=== NO AVAILABILITY DOMAINS CONFIGURED — check OCI_ADS secret ===", flush=True)
        set_output(False)
        return

    for ad in AVAILABILITY_DOMAINS:
        try:
            print(f"=== Trying AD {ad}... ===", flush=True)
            instance = try_launch(compute_client, ad)
            print(f"=== SUCCESS: {instance.id} in {ad} ===", flush=True)
            notify_telegram(
                f"🟢 Caught an instance!\nAD: {ad}\nID: {instance.id}\n"
                f"Check the OCI console for the public IP."
            )
            set_output(True)
            return
        except oci.exceptions.ServiceError as e:
            print(f"=== ServiceError: code={e.code} status={e.status} message={e.message} ===", flush=True)
            if is_capacity_error(e):
                print(f"=== No capacity in {ad} ===", flush=True)
            elif e.status == 429:
                print("=== Rate limited — stopping this round ===", flush=True)
                break
            else:
                print(f"=== UNEXPECTED SERVICE ERROR: {e.code} — {e.message} ===", flush=True)
                notify_telegram(f"🔴 Catcher hit an unexpected error: {e.code} — {e.message}")
                set_output(False)
                sys.exit(1)
        except Exception:
            print("=== UNEXPECTED PYTHON EXCEPTION DURING LAUNCH ATTEMPT ===", flush=True)
            traceback.print_exc()
            set_output(False)
            sys.exit(1)

    print("=== No capacity this round ===", flush=True)
    set_output(False)


if __name__ == "__main__":
    try:
        main()
        print("=== script finished normally ===", flush=True)
    except Exception:
        print("=== UNHANDLED EXCEPTION AT TOP LEVEL ===", flush=True)
        traceback.print_exc()
        sys.exit(1)