#!/usr/bin/env python3
"""Genera el par de claves Ed25519 para firmar las actualizaciones OTA.

- Escribe la clave PÚBLICA en installer/ota_pubkey.txt (se commitea; las apps instaladas la fijan).
- Muestra la clave PRIVADA una sola vez: guárdala como secreto OTA_SIGNING_KEY en GitHub
  (Settings → Secrets and variables → Actions) o con:  gh secret set OTA_SIGNING_KEY
  ¡Nunca la commitees! Quien la tenga puede publicar actualizaciones para tus usuarios.
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "installer"))
import ed25519  # noqa: E402

pub_file = ROOT / "installer" / "ota_pubkey.txt"
if any(ln.strip() and not ln.startswith("#") for ln in pub_file.read_text().splitlines()) and "--force" not in sys.argv:
    sys.exit("Ya hay una clave pública. Rotarla deja sin actualizaciones a quien tenga la anterior "
             "hasta que instale una versión firmada con ella. Usa --force si de verdad quieres.")

seed = secrets.token_bytes(32)
pub = ed25519.public_key(seed)
lines = [ln for ln in pub_file.read_text().splitlines() if ln.startswith("#")]
pub_file.write_text("\n".join([*lines, pub.hex()]) + "\n")
print(f"Clave pública escrita en {pub_file.relative_to(ROOT)}: {pub.hex()}\n")
print("CLAVE PRIVADA (guárdala como secreto OTA_SIGNING_KEY y no la compartas):\n")
print(seed.hex())
