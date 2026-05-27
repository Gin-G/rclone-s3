#!/usr/bin/env python3
"""Quick S3 size/count probe for the tds-data prefix during seed."""
import os
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    endpoint_url="https://boreas.hpc.ucar.edu:6443",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4",
                  s3={"addressing_style": "path"}),
)

paginator = s3.get_paginator("list_objects_v2")
n, sz = 0, 0
for page in paginator.paginate(Bucket="gdex", Prefix="tds-data/"):
    for o in page.get("Contents", []):
        n += 1
        sz += o["Size"]
print(f"{n:>12,} objects   {sz / 2**30:8.2f} GiB")