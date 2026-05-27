#!/usr/bin/env python3
"""
Apply (or update) the S3 lifecycle policy on the gdex bucket.

Rules applied (one per prefix in PREFIXES):
  - NoncurrentVersionExpiration: 90 days
    Expires overwritten/old versions after 90 days. Does NOT touch
    current objects. Bounds the storage cost of having versioning on.

  - AbortIncompleteMultipartUpload: 7 days
    Cleans up orphaned multipart uploads from interrupted backups.

Each prefix gets its own rule scoped to that prefix. To add or remove
a prefix, edit the PREFIXES list at the top of this module.

Currently configured prefixes:
  - gdex-web-data/  (gdex-web PVC backup)
  - tds-data/       (tds-persist PVC backup)

The pgBackRest data at pgdb02/ is NOT covered; pgBackRest manages
its own retention.

Usage (same cred handling as inspect_gdex.py):
    python apply_lifecycle.py --access-key ... --secret-key ...

    # via env
    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \\
        python apply_lifecycle.py

    # from the k8s secret
    python apply_lifecycle.py \\
        --access-key "$(kubectl get secret backup-s3-creds \\
            -o jsonpath='{.data.access_key}' | base64 -d)" \\
        --secret-key "$(kubectl get secret backup-s3-creds \\
            -o jsonpath='{.data.secret_key}' | base64 -d)"

    # see what's currently applied without changing anything
    python apply_lifecycle.py --check-only ...

    # remove all rules
    python apply_lifecycle.py --delete ...
"""

import argparse
import json
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ENDPOINT = "https://boreas.hpc.ucar.edu:6443"
BUCKET = "gdex"

# Prefixes to apply lifecycle rules to. Each gets a separate rule
# scoped to its prefix; rules don't affect anything outside their
# Filter.Prefix. To add a new app, add an entry here.
PREFIXES = [
    "gdex-web-data/",
    "tds-data/",
]

LIFECYCLE = {
    "Rules": [
        {
            "ID": f"{p.rstrip('/')}-noncurrent-90d",
            "Status": "Enabled",
            "Filter": {"Prefix": p},
            "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        }
        for p in PREFIXES
    ]
}


def make_client(ak: str, sk: str):
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def show_current(s3) -> None:
    print(f"Current lifecycle on bucket {BUCKET}:")
    try:
        resp = s3.get_bucket_lifecycle_configuration(Bucket=BUCKET)
        print(json.dumps(resp.get("Rules", []), indent=2, default=str))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            print("  (no lifecycle rules configured)")
        else:
            raise


def show_versioning(s3) -> None:
    resp = s3.get_bucket_versioning(Bucket=BUCKET)
    status = resp.get("Status", "Unset")
    print(f"Bucket versioning status: {status}")
    if status != "Enabled":
        print("  WARNING: versioning is not enabled. The "
              "NoncurrentVersionExpiration rule won't do anything "
              "until versioning is on, since there are no noncurrent "
              "versions to expire.")


def apply_policy(s3) -> None:
    prefixes = ", ".join(repr(p) for p in PREFIXES)
    print(f"\nApplying lifecycle policy ({len(PREFIXES)} rules, "
          f"scopes: {prefixes})...")
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET, LifecycleConfiguration=LIFECYCLE
    )
    print("  OK")


def delete_policy(s3) -> None:
    print(f"\nDeleting lifecycle policy from bucket {BUCKET}...")
    s3.delete_bucket_lifecycle(Bucket=BUCKET)
    print("  OK")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--access-key",
                   default=os.environ.get("AWS_ACCESS_KEY_ID"))
    p.add_argument("--secret-key",
                   default=os.environ.get("AWS_SECRET_ACCESS_KEY"))
    p.add_argument("--check-only", action="store_true",
                   help="show current lifecycle and exit; make no changes")
    p.add_argument("--delete", action="store_true",
                   help="remove the lifecycle policy from the bucket")
    args = p.parse_args()

    if not args.access_key or not args.secret_key:
        sys.exit("error: access/secret key required "
                 "(--access-key/--secret-key or "
                 "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)")

    if args.check_only and args.delete:
        sys.exit("error: --check-only and --delete are mutually exclusive")

    s3 = make_client(args.access_key, args.secret_key)

    print(f"Endpoint : {ENDPOINT}")
    print(f"Bucket   : {BUCKET}")
    print(f"Prefixes : {', '.join(PREFIXES)}")
    print()

    show_versioning(s3)
    print()
    show_current(s3)

    if args.check_only:
        return

    if args.delete:
        print()
        confirm = input(f"Delete lifecycle policy on bucket {BUCKET}? [y/N] ")
        if confirm.lower() != "y":
            sys.exit("aborted")
        delete_policy(s3)
        print()
        show_current(s3)
        return

    print("\nProposed lifecycle:")
    print(json.dumps(LIFECYCLE, indent=2))
    confirm = input("\nApply this policy? [y/N] ")
    if confirm.lower() != "y":
        sys.exit("aborted")

    apply_policy(s3)
    print()
    show_current(s3)


if __name__ == "__main__":
    main()