
from pathlib import Path
import re


def inspect_dump(file_path: Path):
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    print("\n========== SQL DUMP INFORMATION ==========")
    print(f"File: {file_path.name}")
    print(f"Size: {file_path.stat().st_size / (1024 * 1024):.2f} MB")

    # Inspect file header
    with file_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace"
    ) as file:
        print("\n========== FIRST 12 LINES ==========")

        for number, line in enumerate(file, start=1):
            print(f"{number}: {line[:250].rstrip()}")

            if number >= 12:
                break

    # Find the first data-insertion statement without
    # reading the complete dump into memory.
    patterns = [
        b"INSERT INTO",
        b"REPLACE INTO",
        b"LOAD DATA",
    ]

    found_position = None
    found_pattern = None
    overlap = b""
    bytes_read = 0

    with file_path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            combined = overlap + chunk
            lower = combined.lower()

            matches = []

            for pattern in patterns:
                position = lower.find(pattern.lower())

                if position >= 0:
                    matches.append((position, pattern))

            if matches:
                position, pattern = min(matches)
                found_position = bytes_read - len(overlap) + position
                found_pattern = pattern
                break

            overlap = combined[-32:]
            bytes_read += len(chunk)

    print("\n========== DATA STATEMENT ==========")

    if found_position is None:
        print("No INSERT, REPLACE or LOAD DATA statement found.")
        return

    print(f"Statement type: {found_pattern.decode()}")
    print(f"Byte position: {found_position}")

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace"
    ) as file:
        file.seek(found_position)
        preview = file.read(800)

    print("\nFirst 800 characters of the statement:")
    print(preview)

    # Detect SQL dump compression
    print("\n========== FORMAT ==========")

    with file_path.open("rb") as file:
        signature = file.read(2)

    if signature == b"\x1f\x8b":
        print("GZIP compressed file detected.")
    else:
        print("File appears to be an uncompressed SQL text dump.")

    print("\nInspection completed.")


if __name__ == "__main__":
    path = input(
        "\nEnter full path to Dump20260308.sql: "
    ).strip().strip('"')

    inspect_dump(Path(path))
