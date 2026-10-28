import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from gk_vector.palette import (Matcher,load_palette,parse_rgb,update_palette,sha256,
                               version_of,atomic_json,write_color_report,detect_grid)
from gk_vector.pipeline import prepare,vectorize
from palette_fixture import make_palette


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.active=self.root/'pantonic.json'
        make_palette(self.active)
        self.source=self.root/'chart.tif'
        Image.new('RGB',(140,200),(100,110,120)).save(self.source)
        self.grid=patch('gk_vector.palette.detect_grid',return_value=([(10,50),(70,110)],[(10,40),(100,130)]))

    def tearDown(self):
        self.temporary.cleanup()

    def recognizer(self,crops):
        return [('RGB 12 34 56',.999),('One',.999),('RGB 210 220 230',.999),('Two',.999)]

    def test_parser_does_not_guess_ambiguous_or_invalid_rgb(self):
        self.assertEqual(parse_rgb('RGB: 237 241 254'),[237,241,254])
        self.assertEqual(parse_rgb('RGB 221.224 223'),[221,224,223])
        self.assertEqual(parse_rgb('RGB243238231'),[243,238,231])
        self.assertIsNone(parse_rgb('RGB123456'))
        self.assertIsNone(parse_rgb('RGB 999 5 6'))
        self.assertIsNone(parse_rgb('RGB 12 X4 56'))

    def test_import_uses_printed_labels_and_noop_avoids_ocr(self):
        with self.grid:
            result=update_palette(self.source,self.active,recognizer=self.recognizer)
        self.assertEqual(result['status'],'updated')
        catalog=load_palette(self.active)
        self.assertEqual(catalog['entries'][0]['rgb'],[12,34,56])
        self.assertEqual(catalog['entries'][0]['sample_rgb'],[100,110,120])
        result=update_palette(self.source,self.active,recognizer=lambda _:self.fail('unchanged chart reran OCR'))
        self.assertEqual(result['status'],'unchanged')

    def test_bad_import_preserves_active_and_can_be_corrected(self):
        before=self.active.read_bytes()
        def bad(crops):
            rows=self.recognizer(crops)
            rows[0]=('RGB 999 1 2',.99)
            return rows
        with self.grid:
            result=update_palette(self.source,self.active,recognizer=bad)
        self.assertEqual(result['status'],'needs_corrections')
        self.assertEqual(self.active.read_bytes(),before)
        corrections={'source_sha256':sha256(self.source),'entries':{
            'r01c01':{'rgb':[1,2,3]},'r02c01':{'rgb':[4,5,6]}}}
        with self.grid:
            result=update_palette(self.source,self.active,corrections,recognizer=bad)
        self.assertEqual(result['status'],'updated')
        self.assertEqual(load_palette(self.active)['entries'][0]['rgb'],[1,2,3])
        self.assertFalse(self.active.with_suffix('.candidate.json').exists())

    def test_corrections_are_bound_to_the_source(self):
        with self.assertRaisesRegex(ValueError,'source_sha256'):
            update_palette(self.source,self.active,{'source_sha256':'wrong','entries':{}})

    def test_saved_corrections_are_reused_only_for_matching_chart(self):
        corrections={'source_sha256':sha256(self.source),'entries':{'r01c01':{'name':'Corrected Name'}}}
        atomic_json(self.active.with_suffix('.corrections.json'),corrections)
        with self.grid:
            update_palette(self.source,self.active,recognizer=self.recognizer)
        self.assertEqual(load_palette(self.active)['entries'][0]['name'],'Corrected Name')
        Image.new('RGB',(140,200),(1,2,3)).save(self.source)
        with patch('gk_vector.palette.detect_grid',return_value=([(10,50),(70,110)],[(10,40),(100,130)])):
            update_palette(self.source,self.active,recognizer=self.recognizer)
        self.assertEqual(load_palette(self.active)['entries'][0]['name'],'One')

    def test_chart_change_during_import_does_not_publish(self):
        before=self.active.read_bytes()
        def changed(crops):
            Image.new('RGB',(140,200),(1,2,3)).save(self.source)
            return self.recognizer(crops)
        with self.grid, self.assertRaisesRegex(ValueError,'changed during import'):
            update_palette(self.source,self.active,recognizer=changed)
        self.assertEqual(self.active.read_bytes(),before)

    def test_palette_checksum_rejects_manual_changes(self):
        catalog=load_palette(self.active)
        catalog['entries'][0]['rgb']=[1,2,3]
        atomic_json(self.active,catalog)
        with self.assertRaisesRegex(ValueError,'checksum'):
            load_palette(self.active)

    def test_final_paints_and_txt_match_exactly(self):
        catalog=load_palette(self.active)
        matcher=Matcher(catalog)
        svg=ET.fromstring('<svg><path fill="#003172"/><path fill="#fffffe" stroke="#e50a15"/><path fill="none"/></svg>')
        used=matcher.constrain_svg(svg)
        actual={e.get(key) for e in svg.iter() for key in ('fill','stroke') if e.get(key) not in (None,'none')}
        self.assertEqual(actual,{'#003070','#FFFFFF','#E60A14'})
        report=self.root/'colors.txt'
        write_color_report(report,catalog,used,'artwork.svg')
        text=report.read_text()
        for color in actual: self.assertIn(color,text)
        self.assertNotIn('Cyan',text)

    def test_palette_change_does_not_change_existing_job(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(200,160),'#e6e6e6')
        draw=ImageDraw.Draw(image)
        draw.rectangle((10,10,80,145),fill='#003070')
        draw.rectangle((115,10,185,145),fill='#003070')
        source=self.root/'panels.png';image.save(source)
        profile=json.loads((ROOT/'profiles/201-107.json').read_text())
        folder=self.root/'job'
        job=prepare(source,folder,profile,{'pixels':[200,160]},palette_file=self.active)
        old_version=job['palette']['version']
        data=load_palette(self.active)
        data['entries'][0]['rgb']=[255,0,0];data['version']=version_of(data)
        atomic_json(self.active,data)
        report=vectorize(folder,candidate=True)
        self.assertEqual(report['palette']['version'],old_version)
        self.assertIn('#003070',(folder/'candidate/panels.svg').read_text())
        with (folder/'palette.json').open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'Source changed'):
            vectorize(folder,candidate=True)
