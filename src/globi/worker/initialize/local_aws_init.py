"""Initialize the local AWS environment."""

import logging
import os

import boto3
from scythe.settings import ScytheStorageSettings

s3 = boto3.client("s3")

logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)

# list buckets
if __name__ == "__main__":
    bucket_name = ScytheStorageSettings().BUCKET
    # create the bucket if it does not exist
    try:
        region = os.getenv("AWS_DEFAULT_REGION")
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                "LocationConstraint": region,  # pyright: ignore [reportArgumentType]
            },
        )
        logger.info(f"Bucket {bucket_name} created")
    except Exception as e:
        logger.info(f"Bucket {bucket_name} already exists, {e}")
