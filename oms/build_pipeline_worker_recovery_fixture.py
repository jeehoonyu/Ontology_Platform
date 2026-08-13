"""Build and upload a deterministic partitioned fixture for container recovery."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from pathlib import Path

import boto3
import duckdb
from botocore.config import Config
from botocore.exceptions import ClientError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bucket", default="ontology-rehearsal")
    parser.add_argument("--access-key", default="ontology")
    parser.add_argument("--secret-key", default=os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--partitions", type=int, default=32)
    args = parser.parse_args()
    if not args.secret_key:
        raise SystemExit("--secret-key or AWS_SECRET_ACCESS_KEY is required")
    if args.rows < args.partitions or args.partitions < 4 or args.rows % args.partitions:
        raise SystemExit("Rows must divide evenly across at least four partitions")

    run_id = uuid.uuid4().hex[:12]
    prefix = f"production-worker-recovery/{run_id}"
    s3 = boto3.client(
        "s3", endpoint_url=args.endpoint, region_name="us-east-1",
        aws_access_key_id=args.access_key, aws_secret_access_key=args.secret_key,
        config=Config(s3={"addressing_style": "path"}),
    )
    try:
        s3.head_bucket(Bucket=args.bucket)
    except ClientError:
        s3.create_bucket(Bucket=args.bucket)

    rows_per_partition = args.rows // args.partitions
    uploaded_bytes = 0
    with tempfile.TemporaryDirectory(prefix="ontology-worker-fixture-") as directory:
        root = Path(directory)
        for partition in range(args.partitions):
            start = partition * rows_per_partition
            end = start + rows_per_partition
            path = root / f"part-{partition:04d}.parquet"
            connection = duckdb.connect(database=":memory:")
            try:
                connection.execute(
                    f"COPY (SELECT 'asset-' || CAST(i AS VARCHAR) AS asset_id, "
                    f"CAST(i % 100 AS DOUBLE) AS risk_score, CAST(i % 20 AS INTEGER) AS category "
                    f"FROM range({start}, {end}) AS source(i)) TO '{path.as_posix()}' "
                    "(FORMAT PARQUET, COMPRESSION ZSTD)"
                )
            finally:
                connection.close()
            uploaded_bytes += path.stat().st_size
            s3.upload_file(
                str(path), args.bucket,
                f"{prefix}/region=region-{partition:03d}/{path.name}",
            )

    print(json.dumps({
        "run_id": run_id,
        "storage_uri": f"s3://{args.bucket}/{prefix}",
        "rows": args.rows,
        "partitions": args.partitions,
        "uploaded_bytes": uploaded_bytes,
    }))


if __name__ == "__main__":
    main()
