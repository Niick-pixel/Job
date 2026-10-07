#!/usr/bin/env python3
"""Construye una release OTA: tarball reproducible + manifest.json firmado + install.sh.

    OTA_SIGNING_KEY=<hex> python3 scripts/release.py --base-url https://github.com/<owner>/<repo>/releases/download/v0.2.0/

Salida en dist/:  jobtracker-ai-X.Y.Z.tar.gz · manifest.json · install.sh
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "installer"))
import ed25519  # noqa: E402
from jobtracker import canonical_manifest, load_pubkey, parse_version  # noqa: E402


def tracked_files(root: Path) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return sorted(f for f in out.decode().split("\0") if f and (root / f).is_file())


def build_tarball(root: Path, version: str, out: Path) -> Path:
    prefix = f"jobtracker-ai-{version}"
    epoch = int(os.getenv("SOURCE_DATE_EPOCH", "0"))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in tracked_files(root):
            src = root / rel
            info = tar.gettarinfo(str(src), arcname=f"{prefix}/{rel}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = epoch
            info.mode = 0o755 if os.access(src, os.X_OK) else 0o644
            with open(src, "rb") as fh:
                tar.addfile(info, fh)
    path = out / f"{prefix}.tar.gz"
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=epoch, filename="") as gz:
        gz.write(buf.getvalue())
    return path


def changelog_notes(root: Path, version: str) -> str:
    try:
        text = (root / "CHANGELOG.md").read_text()
    except FileNotFoundError:
        return ""
    m = re.search(rf"^## \[?{re.escape(version)}\]?.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    ap.add_argument("--out", default="dist", type=Path)
    ap.add_argument("--base-url", default="", help="URL donde se publicará el tarball (vacío = relativa al manifiesto)")
    args = ap.parse_args()

    root = args.root.resolve()
    version = (root / "VERSION").read_text().strip()
    parse_version(version)
    args.out.mkdir(parents=True, exist_ok=True)

    tar_path = build_tarball(root, version, args.out)
    manifest = {
        "name": "jobtracker-ai",
        "version": version,
        "url": f"{args.base_url}{tar_path.name}",
        "sha256": hashlib.sha256(tar_path.read_bytes()).hexdigest(),
        "size": tar_path.stat().st_size,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "min_macos": "11.0",
        "notes": changelog_notes(root, version),
    }

    pubkey = load_pubkey(root)
    seed_hex = os.getenv("OTA_SIGNING_KEY", "").strip()
    if seed_hex:
        seed = bytes.fromhex(seed_hex)
        if pubkey and ed25519.public_key(seed) != pubkey:
            print("❌ OTA_SIGNING_KEY no corresponde a installer/ota_pubkey.txt", file=sys.stderr)
            return 1
        manifest["signature"] = ed25519.sign(seed, canonical_manifest(manifest)).hex()
    elif pubkey:
        print("❌ installer/ota_pubkey.txt tiene clave pero falta OTA_SIGNING_KEY", file=sys.stderr)
        return 1
    else:
        print("⚠️  Release SIN firmar (configura la clave con scripts/gen_signing_key.py)", file=sys.stderr)

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    shutil.copy2(root / "installer" / "install.sh", args.out / "install.sh")
    print(f"✅ {tar_path.name}  sha256={manifest['sha256'][:12]}…  firmado={'signature' in manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
