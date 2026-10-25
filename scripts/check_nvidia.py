"""Test the NVIDIA API connection and pick a working model.

Usage:  python scripts/check_nvidia.py [--write]

Lists the models your key can use, tries the configured NVIDIA_MODEL first and
then the preferred fallbacks with a tiny real chat call, and reports the first
one that works. With --write it saves that model to NVIDIA_MODEL in .env.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from accessroute import ai_client  # noqa: E402


def main():
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        sys.exit("NVIDIA_API_KEY is not set in .env")
    base = ai_client.NVIDIA_BASE_URL

    # 1. Which models does this key see?
    resp = requests.get(f"{base}/models", headers=ai_client._headers(key), timeout=30)
    print(f"GET {base}/models -> HTTP {resp.status_code}")
    if not resp.ok:
        sys.exit(resp.text[:300])
    ids = [m["id"] for m in resp.json().get("data", [])]
    print(f"{len(ids)} models available")

    # 2. Candidates: configured model, preferred list, then any instruct model.
    configured = os.getenv("NVIDIA_MODEL", "").strip()
    candidates = [configured] + ai_client.PREFERRED_MODELS
    candidates += [i for i in ids if "instruct" in i.lower() and "vision" not in i.lower()][:8]
    seen = set()
    for model in candidates:
        if not model or model in seen or model not in ids:
            continue
        seen.add(model)
        try:
            reply = ai_client._chat(key, model, [{"role": "user", "content": "Say hello in five words."}])
        except Exception as exc:  # report and try the next one
            print(f"  x {model}: {exc}")
            continue
        print(f"  OK {model}: {reply!r}")
        if "--write" in sys.argv:
            env = ROOT / ".env"
            text = env.read_text() if env.exists() else ""
            line = f"NVIDIA_MODEL={model}"
            text = re.sub(r"^NVIDIA_MODEL=.*$", line, text, flags=re.M) if "NVIDIA_MODEL=" in text \
                else text.rstrip("\n") + "\n" + line + "\n"
            env.write_text(text)
            print(f"Saved {line} to .env")
        else:
            print(f"Re-run with --write to save NVIDIA_MODEL={model} to .env")
        return
    sys.exit("No working model found. Check the model list above.")


if __name__ == "__main__":
    main()
