"""Build the demo snapshot through the real public contracts, then export it.

Usage (API + worker + Redis running; uses the dedicated E2E account from web/.env.e2e):
    cd api && ../.venv/Scripts/python scripts/seed_demo.py --api http://localhost:8002

Steps: sign in -> create a scratch workspace -> upload each demo file to private storage with the
student's own token -> confirm (worker extracts, chunks, embeds, proposes the topic map and splits
the practice paper) -> approve all -> match past papers -> export `api/demo/snapshot.json` ->
delete the scratch workspace.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.demo import SNAPSHOT_PATH, export_snapshot, read_demo_file

FILES = [
    ("syllabus.txt", "syllabus"),
    ("class10-science-notes.txt", "notes"),
    ("practice-paper.txt", "past_paper"),
]


def env_file(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
    )


def wait(label: str, check: object, timeout: float = 600) -> None:
    started = time.time()
    while time.time() - started < timeout:
        result = check()  # type: ignore[operator]
        if result:
            print(f"  {label}: ok")
            return
        time.sleep(4)
    raise SystemExit(f"timed out waiting for {label}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    args = parser.parse_args()
    settings = get_settings()
    e2e = env_file(ROOT / "web" / ".env.e2e")
    web = env_file(ROOT / ".env")
    supabase = str(settings.supabase_url).rstrip("/")
    anon = web["NEXT_PUBLIC_SUPABASE_ANON_KEY"].strip()
    token = httpx.post(
        f"{supabase}/auth/v1/token?grant_type=password",
        headers={"apikey": anon},
        json={"email": e2e["E2E_EMAIL"].strip(), "password": e2e["E2E_PASSWORD"].strip()},
        timeout=30,
    )
    token.raise_for_status()
    jwt = token.json()["access_token"]
    api = httpx.Client(base_url=args.api, headers={"authorization": f"Bearer {jwt}"}, timeout=60)

    workspace = api.post(
        "/workspaces", json={"title": "Demo seed (temporary)", "selected_locale": "en"}
    ).json()
    ws = workspace["id"]
    print("scratch workspace", ws)
    try:
        for filename, role in FILES:
            raw = read_demo_file(filename)
            digest = hashlib.sha256(raw).hexdigest()
            intent = api.post(
                "/documents/upload-intent",
                json={
                    "workspace_id": ws,
                    "material_role": role,
                    "filename": filename,
                    "mime_type": "text/plain",
                    "byte_size": len(raw),
                    "checksum_sha256": digest,
                },
            ).json()
            upload = httpx.post(
                f"{supabase}/storage/v1/object/{intent['bucket']}/{intent['storage_path']}",
                headers={
                    "authorization": f"Bearer {jwt}",
                    "apikey": anon,
                    "content-type": "text/plain",
                },
                content=raw,
                timeout=60,
            )
            upload.raise_for_status()
            confirmed = api.post(
                f"/documents/{intent['document_id']}/confirm", json={"checksum_sha256": digest}
            )
            confirmed.raise_for_status()
            print("  uploaded", filename)
        wait(
            "documents ready",
            lambda: all(
                d["state"] in ("ready", "failed")
                for d in api.get(f"/documents/workspace/{ws}").json()
            ),
        )
        failed = [
            d["filename"]
            for d in api.get(f"/documents/workspace/{ws}").json()
            if d["state"] != "ready"
        ]
        if failed:
            raise SystemExit(f"processing failed: {failed}")
        wait(
            "topic proposal",
            lambda: (
                api.get(f"/topics/workspace/{ws}/jobs/propose").json()["state"]
                in ("succeeded", "failed")
            ),
        )
        state = api.get(f"/topics/workspace/{ws}/jobs/propose").json()
        if state["state"] != "succeeded":
            raise SystemExit(f"topic proposal failed: {state.get('error_code')}")
        if not api.get(f"/topics/workspace/{ws}").json():
            raise SystemExit("no topics proposed")
        wait(
            "past paper split",
            lambda: (
                api.get(f"/topics/workspace/{ws}/jobs/segment_past_paper").json()["state"]
                in ("succeeded", "failed")
            ),
        )
        state = api.get(f"/topics/workspace/{ws}/jobs/segment_past_paper").json()
        if state["state"] != "succeeded":
            raise SystemExit(f"past paper split failed: {state.get('error_code')}")
        print("  approved", api.post(f"/topics/workspace/{ws}/approve-all").json())
        api.post(f"/topics/workspace/{ws}/map-past-papers").raise_for_status()
        wait(
            "past paper mapping",
            lambda: (
                api.get(f"/topics/workspace/{ws}/jobs/map_past_papers").json()["state"]
                in ("succeeded", "failed")
            ),
        )
        state = api.get(f"/topics/workspace/{ws}/jobs/map_past_papers").json()
        if state["state"] != "succeeded":
            raise SystemExit(f"past paper mapping failed: {state.get('error_code')}")
        with SessionLocal() as session:
            snapshot = export_snapshot(session, UUID(ws))
        SNAPSHOT_PATH.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(
            f"wrote {SNAPSHOT_PATH} — {len(snapshot['documents'])} documents, {len(snapshot['topics'])} topics, "
            f"{len(snapshot['links'])} links, {len(snapshot['past_paper_questions'])} past-paper questions"
        )
    finally:
        print("cleanup:", api.delete(f"/workspaces/{ws}").status_code)


if __name__ == "__main__":
    main()
