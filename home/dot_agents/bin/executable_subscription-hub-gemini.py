#!/usr/bin/env python3
"""Configure OpenCode to use the subscription hub's Antigravity models."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://burnbutu.royal-burbot.ts.net:8317/v1"
PROVIDER = "antigravity_hub"
MODELS = {
    "gemini-4-argon-high": "Gemini 4 Argon High (Hub)",
    "gemini-4-hydrogen-xhigh": "Gemini 4 Hydrogen XHigh (Hub)",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite (Hub)",
}


def check_hub(key):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    prompt = {
        "model": "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "Reply with exactly HUB_OK"}],
    }
    with urlopen(Request(BASE_URL + "/chat/completions", json.dumps(prompt).encode(), headers),
                 timeout=30) as response:
        message = json.load(response)["choices"][0]["message"]
    if message["content"].strip() != "HUB_OK":
        raise ValueError("Gemini hub smoke request returned an unexpected reply")


def configure(path, key_path, verify):
    original = path.read_bytes() if path.exists() else None
    config = json.loads(original) if original is not None else {}
    if PROVIDER in config.get("disabled_providers", []):
        raise ValueError("the hub provider is explicitly disabled in OpenCode")
    if "enabled_providers" in config and PROVIDER not in config["enabled_providers"]:
        raise ValueError("the hub provider is absent from the OpenCode provider allowlist")

    providers = config.setdefault("provider", {})
    provider = {
        "name": "Antigravity Hub",
        "npm": "@ai-sdk/openai-compatible",
        "options": {
            "baseURL": BASE_URL,
            "apiKey": "{file:" + key_path.as_posix() + "}",
        },
        "models": {
            model: {"name": name, "tool_call": True}
            for model, name in MODELS.items()
        },
    }
    if PROVIDER in providers:
        if providers[PROVIDER] != provider:
            raise ValueError("existing OpenCode hub provider differs from the expected configuration")
        return
    if verify:
        raise ValueError("OpenCode hub provider is missing")

    providers[PROVIDER] = provider
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".opencode-hub-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(config, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError("OpenCode configuration changed during installation; retry")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Check setup without writing files")
    args = parser.parse_args()
    home = Path.home()
    key_path = home / ".config/cliproxy/personal/access-key"
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "opencode"
    try:
        key = key_path.read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError("subscription hub key file is empty")
        check_hub(key)
        configure(config_dir / "opencode.json", key_path, args.verify)
    except HTTPError as error:
        parser.exit(1, f"Gemini hub smoke request failed with HTTP {error.code}\n")
    except URLError as error:
        parser.exit(1, f"Gemini hub connection failed: {error.reason}\n")
    except (OSError, ValueError, KeyError, IndexError, AttributeError) as error:
        parser.exit(1, f"Gemini hub setup failed: {error}\n")
    print("OpenCode Gemini hub configured; live Gemini smoke request passed")


if __name__ == "__main__":
    main()
