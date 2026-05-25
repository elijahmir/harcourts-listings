"""VaultRE CLI wrapper.

Designed to be called by the consultant Claude via Bash. Subcommands:

    vaultre-cli search "158 Preservation Drive"
        → JSON array of property summaries (id, address, status, agent)

    vaultre-cli get 35489499
        → JSON object with bedrooms/bathrooms/etc., heading, descriptions

    vaultre-cli photos 35489499
        → JSON {photographs: [...], floor_plans: [...]} of photo metadata

    vaultre-cli download 35489499 consultants/wendy-squibb/sessions/session-abc/vaultre-photos
        → Downloads every photo + floor plan into <dest>/ and prints the
          local paths. Floor plans land in <dest>/floor-plans/ to mirror
          the chat-upload convention so the same workflow.md Step 1.3
          inspection rule applies.

Output is always JSON-lines or human-readable text — caller (Claude) parses
or just reads. Errors exit non-zero with a structured JSON error to stderr.

Run via:

    python -m services.backend.app.vaultre_cli <subcmd> <args>

or through the convenience shell wrapper at scripts/vaultre.sh.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .vaultre import VaultRE, download_photo


def _asdict(obj) -> dict:
    """Dataclass → dict, dropping the raw passthrough field if present."""
    d = dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else dict(obj)
    d.pop("raw", None)
    return d


def cmd_search(args: argparse.Namespace) -> int:
    v = VaultRE()
    try:
        results = v.search_by_address(args.term, limit=args.limit)
    finally:
        v.close()
    print(json.dumps([_asdict(r) for r in results], indent=2))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    v = VaultRE()
    try:
        detail = v.get_property(args.property_id)
    finally:
        v.close()
    print(json.dumps(_asdict(detail), indent=2, default=str))
    return 0


def cmd_photos(args: argparse.Namespace) -> int:
    v = VaultRE()
    try:
        photos, plans = v.get_property_photos(args.property_id)
    finally:
        v.close()
    print(json.dumps(
        {
            "photographs": [_asdict(p) for p in photos],
            "floor_plans":  [_asdict(p) for p in plans],
        },
        indent=2,
    ))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """Download every photo + floor plan locally so Claude can Read them
    with vision. Floor plans go into a `floor-plans/` subfolder so the
    classification step in workflow.md Step 1.3 is unambiguous."""
    v = VaultRE()
    try:
        photos, plans = v.get_property_photos(args.property_id)
    finally:
        v.close()

    dest = Path(args.dest_dir).resolve()
    floor_plans_dir = dest / "floor-plans"
    written: list[dict] = []
    errors: list[dict] = []

    for p in photos:
        local = dest / f"vaultre-{p.id}.jpg"
        try:
            bytes_ = download_photo(p.url, local)
            written.append({"id": p.id, "kind": "photograph",
                            "path": str(local.relative_to(Path.cwd())),
                            "bytes": bytes_})
        except Exception as exc:  # noqa: BLE001 — surface back to caller
            errors.append({"id": p.id, "url": p.url, "error": str(exc)})

    for p in plans:
        local = floor_plans_dir / f"vaultre-{p.id}.jpg"
        try:
            bytes_ = download_photo(p.url, local)
            written.append({"id": p.id, "kind": "floorplan",
                            "path": str(local.relative_to(Path.cwd())),
                            "bytes": bytes_})
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": p.id, "url": p.url, "error": str(exc)})

    print(json.dumps(
        {
            "downloaded": written,
            "errors": errors,
            "summary": {
                "photographs": sum(1 for w in written if w["kind"] == "photograph"),
                "floor_plans": sum(1 for w in written if w["kind"] == "floorplan"),
                "failures":    len(errors),
            },
        },
        indent=2,
    ))
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vaultre-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="search properties by address fragment")
    p_search.add_argument("term", help="address fragment, e.g. '158 Preservation'")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_get = sub.add_parser("get", help="fetch full property record by ID")
    p_get.add_argument("property_id", type=int)
    p_get.set_defaults(func=cmd_get)

    p_photos = sub.add_parser("photos", help="list photo URLs (split by type)")
    p_photos.add_argument("property_id", type=int)
    p_photos.set_defaults(func=cmd_photos)

    p_dl = sub.add_parser("download", help="download every photo + floor plan locally")
    p_dl.add_argument("property_id", type=int)
    p_dl.add_argument("dest_dir", help="where to save (e.g. consultants/wendy-squibb/sessions/session-X/vaultre-photos)")
    p_dl.set_defaults(func=cmd_download)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyError as e:
        # Missing required env var.
        print(json.dumps({"error": f"missing env: {e}"}), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
