"""
Throwaway script to manually verify storage.py against real MinIO.
Not part of the app — delete once storage is confirmed working.

Usage:
    python scratch_test_storage.py /path/to/your/resume.pdf
"""
import sys
import uuid
from pathlib import Path

from app.services.storage import upload_file, download_file, StorageError


def main():
    if len(sys.argv) != 2:
        print("Usage: python scratch_test_storage.py <path-to-file>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    file_bytes = file_path.read_bytes()
    fake_candidate_id = str(uuid.uuid4())

    print(f"File: {file_path.name}, {len(file_bytes)} bytes")
    print(f"Fake candidate_id: {fake_candidate_id}")
    print("-" * 60)

    try:
        storage_key = upload_file(fake_candidate_id, file_path.name, file_bytes)
        print(f"Uploaded. storage_key = {storage_key}")

        downloaded_bytes = download_file(storage_key)
        print(f"Downloaded {len(downloaded_bytes)} bytes")

        assert downloaded_bytes == file_bytes, "Downloaded bytes don't match original!"
        print("✅ Round-trip verified — downloaded bytes match original exactly")

    except StorageError as e:
        print(f"❌ Storage error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()