import argparse
import json
import re
import sys
from pathlib import Path

from .pipeline import approve, load_job, prepare, vectorize
from .corel import export_cdr
from . import config
from .palette import update_palette
from .update import update_tool

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="Panel reconstruction handoff and vector export")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser('update',help='Pull origin/main; restart the app to finish installation')
    p = sub.add_parser("update-palette", help="Rebuild pantonic from printed RGB labels; preserve active palette if OCR is unresolved")
    p.add_argument("--source", default="docs/pantonic.tif")
    p.add_argument("--destination", default="palettes/pantonic.json")
    p.add_argument("--corrections-file", help="JSON with source_sha256 and entries keyed by r01c01 identifiers")
    p.add_argument("--force", action="store_true", help="Repeat OCR even when chart and corrections are unchanged")
    p = sub.add_parser("setup", help="Initial setup or adjustment of saved defaults")
    p.add_argument("--show", action="store_true")
    p.add_argument("--defaults", action="store_true", help="Initialize with defaults; preserve existing settings")
    p.add_argument("--settings-file", help="JSON patch: output folder, templates, SVG properties and export defaults")
    p = sub.add_parser("prepare")
    p.add_argument("image")
    p.add_argument("job", nargs="?", help="Optional explicit job path; otherwise use setup defaults")
    p.add_argument("--design", help="Design identifier for job and filenames; defaults to image stem")
    p.add_argument("--revision", default="r01")
    p.add_argument("--profile", help="Override the configured default profile")
    p.add_argument("--overrides", default="{}", help="JSON settings overrides")
    p.add_argument("--overrides-file", help="JSON file of settings overrides")
    p.add_argument("--mask", help="Optional combined two-panel grayscale mask")
    p = sub.add_parser("approve")
    p.add_argument("job")
    p.add_argument("--note", required=True, help="Actual client approval text")
    p.add_argument("--colors-approved", action="store_true", help="Client explicitly approved the proposed color selection as well as artwork")
    for name in ("vectorize", "export-cdr"):
        p = sub.add_parser(name)
        p.add_argument("job")
        p.add_argument("--candidate", action="store_true", help="Test a draft; does not record client approval")
    p = sub.add_parser("status")
    p.add_argument("job")
    sub.add_parser("serve")
    args = parser.parse_args()
    try:
        if args.command == 'update':
            result=update_tool(ROOT)
        elif args.command == "update-palette":
            corrections = json.loads(Path(args.corrections_file).read_text(encoding="utf-8")) if args.corrections_file else None
            result = update_palette(ROOT / args.source, ROOT / args.destination, corrections, args.force,
                                    progress=lambda row,total: print(f"OCR row {row}/{total}",file=sys.stderr,flush=True))
        elif args.command == "setup":
            if args.show:
                try:
                    result = {"configured": True, **config.describe(ROOT, config.read_config(ROOT))}
                except ValueError as error:
                    if (ROOT / config.CONFIG_NAME).exists():
                        raise
                    result = {"configured": False, "defaults":config.DEFAULTS, "next_step":str(error)}
            elif args.defaults or args.settings_file:
                patch = json.loads(Path(args.settings_file).read_text(encoding="utf-8")) if args.settings_file else {}
                result = config.configure(ROOT, patch)
            else:
                raise ValueError("Use setup --defaults for initial defaults, --settings-file for adjustments, or --show")
        elif args.command == "prepare":
            preferences = config.read_config(ROOT)
            profile = json.loads((ROOT / (args.profile or preferences["profile"])).read_text(encoding="utf-8"))
            overrides = json.loads(Path(args.overrides_file).read_text(encoding="utf-8")) if args.overrides_file else json.loads(args.overrides)
            svg = config.merge(preferences["svg"], overrides.pop("svg", {}))
            overrides = {**preferences["overrides"], **overrides, "svg":svg}
            design = args.design or re.sub(r"[^\w-]+", "_", Path(args.image).stem)
            folder = Path(args.job) if args.job else config.job_path(ROOT, preferences, design, args.revision)
            identity = {"design":design, "revision":args.revision,
                        "export_names":config.export_names(preferences, design, args.revision),
                        "configuration":preferences}
            result = prepare(args.image, folder, profile, overrides, args.mask, identity, ROOT / preferences["palette_file"])
            result = {"job_folder":str(folder.resolve()), **result}
        elif args.command == "approve":
            result = approve(args.job, args.note, args.colors_approved)
        elif args.command == "vectorize":
            result = vectorize(args.job, args.candidate)
        elif args.command == "export-cdr":
            result = export_cdr(args.job, args.candidate)
        elif args.command == "status":
            result = load_job(args.job)[1]
        else:
            from .server import main as serve
            serve()
            return
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
