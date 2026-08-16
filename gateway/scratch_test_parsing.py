"""
Throwaway script to manually verify extract_text() against a real file.
Not part of the app — delete once parsing is confirmed working.

Usage:
    python scratch_test_parsing.py /path/to/your/resume.pdf
"""
import sys
from pathlib import Path

from app.services.parsing import extract_text
from app.core.exceptions import GuardScreenError


def main():
    if len(sys.argv) != 2:
        print("Usage: python scratch_test_parsing.py <path-to-file>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    file_type = file_path.suffix.lstrip(".").lower()
    file_bytes = file_path.read_bytes()

    print(f"File: {file_path.name}")
    print(f"Detected file_type: {file_type}")
    print(f"Size: {len(file_bytes)} bytes")
    print("-" * 60)

    try:
        text = extract_text(file_bytes, file_type)
    except GuardScreenError as e:
        print(f"Extraction failed: {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"Extracted {len(text)} characters, {len(text.split())} words")
    print("-" * 60)
    print(text[:1000])
    print("..." if len(text) > 1000 else "")


if __name__ == "__main__":
    main()