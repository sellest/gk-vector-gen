import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gk_vector.pipeline import prepare, approve, vectorize, resolve_settings, SVG
from gk_vector.server import local
from gk_vector import config as preferences


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = json.loads((ROOT / "profiles/201-107.json").read_text())
        self.image = self.root / "panels.png"
        image = Image.new("RGB", (400,300), "#e6e6e6")
        draw = ImageDraw.Draw(image)
        for x in (30,230):
            draw.polygon([(x,20),(x+30,20),(x+45,60),(x+80,60),(x+95,20),(x+120,20),
                          (x+140,270),(x,270)], fill="#003070", outline="black")
            draw.rectangle((x+45,100,x+75,110), fill="white")
        image.save(self.image)

    def tearDown(self):
        self.temp.cleanup()

    def job(self):
        folder = self.root / "job"
        prepare(self.image, folder, self.profile, {"pixels":[400,300], "trace_max_dimension":400})
        return folder

    def test_default_pixels_and_dpi_change(self):
        self.assertEqual(resolve_settings(self.profile)["pixels"], [6727,5302])
        doubled = resolve_settings(self.profile, {"dpi":300})
        self.assertEqual(doubled["pixels"], [13454,10604])
        self.assertEqual(doubled["canvas_mm"], self.profile["canvas_mm"])

    def test_conflicting_or_invalid_settings(self):
        for overrides in ({"dpi":0}, {"canvas_mm":[float('nan'),10]}, {"pixels":[-1,5]},
                          {"canvas_mm":[100,100],"pixels":[200,300]}, {"typo":12}):
            with self.assertRaises(ValueError):
                resolve_settings(self.profile, overrides)

    def test_masks_preserve_white_logo_and_separate_panels(self):
        job = self.job()
        mask = Image.open(job / "front-mask.png")
        self.assertEqual(mask.getpixel((80,105)), 255)
        self.assertEqual(mask.getpixel((240,105)), 0)
        self.assertEqual(mask.getpixel((10,10)), 0)

    def test_unapproved_production_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            vectorize(self.job())

    def test_changed_source_invalidates_approval(self):
        job = self.job()
        approve(job, "Client approves the artwork and masks")
        with (job / "clean.png").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            vectorize(job)

    def test_real_vectorization_export_and_metadata(self):
        job = self.job()
        result = vectorize(job, candidate=True)
        self.assertEqual(result["embedded_rasters"], 0)
        self.assertGreater(result["path_count"], 2)
        self.assertIsNone(json.loads((job / "job.json").read_text())["approval"])
        root = ET.parse(job / "candidate/panels.svg").getroot()
        self.assertFalse(root.findall(f".//{{{SVG}}}image"))
        with Image.open(job / "candidate/panels.tif") as image:
            self.assertEqual(image.size, (400,300))
            self.assertAlmostEqual(image.info["dpi"][0],150,places=2)
            self.assertEqual(image.tag_v2[259],5)
        approve(job, "Looks good, use these panels and masks")
        self.assertEqual(vectorize(job)["status"], "exported")

    def test_failed_conversion_is_retryable(self):
        job = self.job()
        with patch("gk_vector.pipeline.vtracer.convert_image_to_svg_py", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                vectorize(job, candidate=True)
        self.assertFalse((job / "candidate").exists())
        self.assertEqual(vectorize(job, candidate=True)["status"], "candidate")

    def test_actual_export_with_dimension_and_dpi_overrides(self):
        job = self.root / "custom"
        prepare(self.image, job, self.profile, {"dpi":75, "canvas_mm":[101.6,76.2]})
        vectorize(job, candidate=True)
        with Image.open(job / "candidate/panels.tif") as image:
            self.assertEqual(image.size, (300,225))
            self.assertAlmostEqual(image.info["dpi"][0],75,places=2)

    def test_existing_job_cannot_be_overwritten(self):
        job = self.job()
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare(self.image, job, self.profile)

    def test_mcp_paths_stay_inside_workspace(self):
        with self.assertRaisesRegex(ValueError,"within"):
            local("../outside-project")

    def test_stdio_mcp_handshake_and_tool_execution(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise():
            workspace = self.root / "workspace"
            (workspace / "profiles").mkdir(parents=True)
            shutil.copyfile(ROOT/"profiles/201-107.json", workspace/"profiles/201-107.json")
            image = workspace / "panels.png"
            shutil.copyfile(self.image, image)
            config = StdioServerParameters(command=sys.executable, args=[str(ROOT/"run.py"), "serve"], cwd=str(ROOT),
                                           env={"GK_VECTOR_ROOT":str(workspace)})
            async with stdio_client(config) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertIn("prepare_panels", {t.name for t in tools.tools})
                    response = await session.call_tool("panel_job_status", {"job":"../outside-project"})
                    self.assertTrue(response.isError)
                    response = await session.call_tool("prepare_panels", {"image":str(image)})
                    self.assertTrue(response.isError)
                    response = await session.call_tool("configure_workspace", {"settings":{
                        "output_folder":str(self.root/"external-artwork"),
                        "filename_template":"{design}-{revision}.{ext}",
                        "svg":{"units":"px", "background":"transparent", "trace_mode":"polygon", "precision":1}}})
                    self.assertFalse(response.isError)
                    response = await session.call_tool("prepare_panels", {
                        "image":str(image), "design":"sample", "revision":"r02",
                        "overrides":{"pixels":[400,300], "trace_max_dimension":400}})
                    self.assertFalse(response.isError)
                    job = str(self.root/"external-artwork/sample/r02")
                    response = await session.call_tool("configure_workspace", {"settings":{"svg":{"background":"solid"}}})
                    self.assertFalse(response.isError)
                    response = await session.call_tool("vectorize_panels", {"job":job,"candidate":True})
                    self.assertFalse(response.isError)
                    report = json.loads((Path(job)/"candidate/report.json").read_text())
                    self.assertEqual(report["embedded_rasters"],0)
                    self.assertEqual(report["status"],"candidate")
                    self.assertEqual(report["settings"]["svg"]["background"],"transparent")
                    svg = ET.parse(Path(job)/"candidate/sample-r02.svg").getroot()
                    self.assertEqual(svg.get("width"),"400")
                    self.assertFalse(svg.findall(f"./{{{SVG}}}rect"))
                    with Image.open(Path(job)/"candidate/sample-r02.tif") as raster:
                        self.assertEqual(raster.getpixel((0,0)),(230,230,230))
        asyncio.run(exercise())

    def test_initial_setup_and_incremental_adjustment(self):
        with self.assertRaisesRegex(ValueError,"Initial setup"):
            preferences.read_config(self.root)
        preferences.configure(self.root, {"profile":str(ROOT/"profiles/201-107.json"),
                                         "output_folder":"artwork", "svg":{"precision":2},
                                         "overrides":{"dpi":75}})
        result = preferences.configure(self.root, {"svg":{"units":"px"}, "overrides":{"gradient_step":20}})
        self.assertEqual(result["settings"]["svg"]["precision"],2)
        self.assertEqual(result["settings"]["overrides"]["dpi"],75)
        self.assertEqual(result["example_exports"]["svg"],"example_r01.svg")
        self.assertEqual(result["example_job"],str(self.root/"artwork/example/r01"))

    def test_invalid_templates_do_not_replace_configuration(self):
        preferences.configure(self.root, {"profile":str(ROOT/"profiles/201-107.json")})
        before = (self.root/preferences.CONFIG_NAME).read_bytes()
        for patch in ({"filename_template":"../{design}.{ext}"}, {"filename_template":"{design.__class__}.{ext}"},
                      {"filename_template":"{design}.svg"}, {"job_template":"../{design}"},
                      {"filename_template":"CON.{ext}"}, {"svg":{"precision":8}},
                      {"svg":{"unsupported":True}}, {"overrides":{"dpi":-20}}):
            with self.assertRaises(ValueError):
                preferences.configure(self.root,patch)
            self.assertEqual((self.root/preferences.CONFIG_NAME).read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
