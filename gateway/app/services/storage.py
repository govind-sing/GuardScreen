import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.core.exceptions import GuardScreenError


class StorageError(GuardScreenError):
    """Raised when an object storage operation fails."""


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_root_user,
        aws_secret_access_key=settings.minio_root_password,
    )


def ensure_bucket_exists() -> None:
    client = _get_client()
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=settings.minio_bucket)
        else:
            raise StorageError(f"Could not verify/create bucket: {e}") from e


def upload_file(candidate_id: str, original_filename: str, file_bytes: bytes) -> str:
    """
    Uploads raw file bytes, returns the storage_key used.
    Key shape: {candidate_id}/{original_filename}
    """
    ensure_bucket_exists()
    storage_key = f"{candidate_id}/{original_filename}"

    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.minio_bucket,
            Key=storage_key,
            Body=file_bytes,
        )
    except ClientError as e:
        raise StorageError(f"Upload failed for key {storage_key}: {e}") from e

    return storage_key


def download_file(storage_key: str) -> bytes:
    client = _get_client()
    try:
        response = client.get_object(Bucket=settings.minio_bucket, Key=storage_key)
        return response["Body"].read()
    except ClientError as e:
        raise StorageError(f"Download failed for key {storage_key}: {e}") from e