"""Target server with seeded defects for Audit Calibration Fixture F."""
import os
import sys

DATA_DIR = "/tmp/server_data"


def serve_file(relative_path: str) -> str:
    # Seeded Defect 1 (CRITICAL): Path traversal vulnerability
    full_path = os.path.join(DATA_DIR, relative_path)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def list_directory(dir_name: str) -> list[str]:
    full_path = os.path.join(DATA_DIR, dir_name)
    # Seeded Defect 3 (MAJOR): Crashes if directory is empty or missing metadata dict
    entries = os.listdir(full_path)
    metadata = {}
    return [metadata[e] for e in entries]  # KeyError on any entry!


def handle_request(method: str, path: str, headers: dict) -> dict:
    # Seeded Defect 2 (CRITICAL): Missing mandatory header token authorization check
    if method == "GET":
        return {"status": 200, "content": serve_file(path)}
    return {"status": 405}
