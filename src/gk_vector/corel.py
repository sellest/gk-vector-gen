"""Optional native CDR exporter. Requires Windows and licensed CorelDRAW.

The adapter is deliberately separate from the tested SVG/TIFF path. SVG import
and version compatibility must be verified on the installed CorelDRAW version.
"""
import json
from pathlib import Path


def export_cdr(folder: str | Path, candidate: bool = False) -> dict:
    folder = Path(folder).resolve()
    report_path = folder / ("candidate" if candidate else "production") / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    names = report.get("artifacts", {"svg":"panels.svg", "cdr":"panels.cdr"})
    output = report_path.parent / names["cdr"]
    if output.exists():
        raise ValueError("CDR already exists; use a new revision")
    app = doc = None
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        # A separate instance avoids changing an existing user document/session.
        app = win32com.client.DispatchEx("CorelDRAW.Application")
        app.Visible = False
        doc = app.OpenDocument(str(report_path.parent / names["svg"]))
        options = app.CreateStructSaveAsOptions()
        options.Version = int(report["settings"]["cdr_version"])
        doc.SaveAs(str(output), options)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("CorelDRAW returned without creating a CDR")
        result = {"status": "saved_needs_visual_verification", "path": str(output),
                  "reason": "Open the CDR in CorelDRAW and compare clipping, colors and gradients with vector-preview.png."}
    except Exception as error:
        result = {"status": "unavailable_or_failed", "reason": str(error),
                  "next_step": "Install/activate CorelDRAW with its Windows automation components, then retry export-cdr."}
    finally:
        if doc is not None:
            try:
                doc.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except (NameError, AttributeError):
            pass
    report["cdr"] = result
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return result
