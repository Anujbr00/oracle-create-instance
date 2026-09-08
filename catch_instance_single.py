#!/usr/bin/env python3
"""
Oracle Cloud Always Free ARM (A1.Flex) capacity catcher — single-attempt mode.

Meant to be invoked once per run by an external scheduler (GitHub Actions
cron), not looped internally. Each invocation:
  1. Checks whether the target instance already exists (idempotent — safe
     to re-run even right after a success, before the schedule gets disabled).
  2. If not, tries a launch in each configured Availability Domain once.
  3. On success: notifies Telegram, sets a `caught=true` GitHub Actions
     output (the workflow uses this to disable further scheduled runs).
  4. On capacity/rate-limit response: exits quietly, exit code 0 — the next
     scheduled run retries.
  5. On an unexpected error: notifies Telegram and exits non-zero so it
     shows up as a failed run in the Actions log.

All config comes from environment variables — the workflow sets these from
GitHub Actions secrets, nothing is hardcoded here.
"""

import os
import sys
import logging

import oci
import requests

COMPARTMENT_ID = os.environ["OCI_COMPARTMENT_ID"]
SUBNET_ID = os.environ["OCI_SUBNET_ID"]
AVAILABILITY_DOMAINS = os.environ["OCI_ADS"].split(",")
IMAGE_ID = os.environ["OCI_IMAGE_ID"]
SSH_PUBLIC_KEY = os.environ["SSH_PUBLIC_KEY"]  # raw key contents, not a path
SHAPE = os.getenv("OCI_SHAPE", "VM.Standard.A1.Flex")
OCPUS = float(os.getenv("OCI_OCPUS", "1"))
MEMORY_GB = float(os.getenv("OCI_MEMORY_GB", "6"))