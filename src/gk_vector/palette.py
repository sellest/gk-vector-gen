"""Import the printed RGB catalog and constrain SVG paints to that catalog."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request
import html

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageOps, ImageDraw, ImageCms

DEFAULT_PALETTE = Path(__file__).resolve().parents[2] / "palettes/pantonic.json"
OCR_MODEL_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx"
OCR_MODEL_SHA256 = "e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318"
IMPORTER = "pantonic-grid-v3/rapidocr-1.4.4/en-ppocrv4"


def ensure_ocr_model(directory: Path) -> Path:
    directory.mkdir(parents=True,exist_ok=True)
    model=directory/'en_PP-OCRv4_rec_mobile.onnx'
    if model.exists() and sha256(model)==OCR_MODEL_SHA256:
        return model
    with tempfile.NamedTemporaryFile(dir=directory,suffix='.download',delete=False) as stream:
        temporary=Path(stream.name)
    try:
        with urllib.request.urlopen(OCR_MODEL_URL,timeout=45) as response, temporary.open('wb') as stream:
            while block:=response.read(1024*1024): stream.write(block)
        if sha256(temporary)!=OCR_MODEL_SHA256:
            raise ValueError('English OCR model checksum mismatch')
        temporary.replace(model)
    finally:
        temporary.unlink(missing_ok=True)
    return model


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".palette-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, indent=2, ensure_ascii=False)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def version_of(data: dict) -> str:
    payload = {"source_sha256":data["source_sha256"], "color_space":"sRGB",
               "entries":[{k:e[k] for k in ("id","name","rgb")} for e in data["entries"]]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_palette(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("color_space") != "sRGB" or not data.get("entries"):
        raise ValueError("Invalid or empty palette catalog")
    ids = set()
    for entry in data["entries"]:
        if entry["id"] in ids or not isinstance(entry["name"],str) or not entry["name"].strip():
            raise ValueError("Invalid palette identifier or name")
        ids.add(entry["id"])
        if len(entry["rgb"]) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in entry["rgb"]):
            raise ValueError(f"Invalid RGB for {entry['id']}")
    if data.get("version") != version_of(data):
        raise ValueError("Palette checksum mismatch; regenerate with update-palette")
    return data


def _runs(mask: np.ndarray) -> list[tuple[int,int]]:
    edges = np.diff(np.r_[False,mask,False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1).tolist(),np.flatnonzero(edges == -1).tolist()))


def detect_grid(image: Image.Image) -> tuple[list, list]:
    """Detect rectangular swatch rows/columns; refuse a nonrectangular chart."""
    width, height = image.size
    best = []
    for y in range(max(1,height//200), max(2,height//12), max(1,height//500)):
        row = np.array(image.crop((0,y,width,y+1)))[0]
        spans = [(a,b) for a,b in _runs(np.any(row < 254,axis=1)) if width*.008 < b-a < width*.05]
        if len(spans) > len(best):
            best = spans
    if len(best) < 2:
        raise ValueError("Could not detect swatch columns")
    columns = best
    row_candidates = []
    for a,b in columns[:3]:
        x = (a+b)//2
        col = np.array(image.crop((x,0,x+1,height)))[:,0]
        rows = [(a,b) for a,b in _runs(np.any(col < 254,axis=1)) if height*.008 < b-a < height*.05]
        row_candidates.append(rows)
    rows = max(row_candidates, key=len)
    if len(rows) < 2:
        raise ValueError("Could not detect swatch rows")
    return columns, rows


def parse_rgb(text: str) -> list[int] | None:
    match = re.match(r"^\s*RGB[\s:_]*(.*?)[\s.,:;_-]*$",text,re.I)
    if not match or re.search(r"[^\d\s,.:_]",match[1]):
        return None
    chunks = re.findall(r"\d+",match[1])
    candidates = []
    def split(chunk, count):
        if count == 0:
            return [[]] if not chunk else []
        results = []
        for n in range(1,min(3,len(chunk))+1):
            head=chunk[:n]
            if (len(head)>1 and head[0]=='0') or int(head)>255:
                continue
            for tail in split(chunk[n:],count-1):
                results.append([int(head),*tail])
        return results
    def combine(index, values):
        if index == len(chunks):
            if len(values)==3: candidates.append(tuple(values))
            return
        for count in range(1,4-len(values)):
            for values2 in split(chunks[index],count):
                combine(index+1,values+values2)
    combine(0,[])
    candidates=set(candidates)
    return list(next(iter(candidates))) if len(candidates)==1 else None


def _label(image, x, end, bottom, gap, name=False):
    crop=image.crop((x-3,bottom+1,end+22,bottom+gap-3)).convert("RGB")
    array=np.array(crop)
    lines=_runs(np.any(array.min(axis=2)<100,axis=1))
    if len(lines)>=2:
        start,stop=(lines[1][0],lines[-1][1]) if name else lines[0]
        crop=crop.crop((0,max(0,start-2),crop.width,min(crop.height,stop+2)))
    array=np.array(crop)
    ys,xs=np.where(array.min(axis=2)<100)
    if len(xs):
        crop=crop.crop((max(0,int(xs.min())-2),max(0,int(ys.min())-2),
                        min(crop.width,int(xs.max())+3),min(crop.height,int(ys.max())+3)))
    crop=ImageOps.expand(crop,border=3,fill="white")
    crop=crop.resize((crop.width*2,crop.height*2),Image.Resampling.LANCZOS)
    return np.array(crop)[:,:,::-1].copy()


def update_palette(source: str | Path, destination: str | Path = DEFAULT_PALETTE,
                   corrections: dict | None = None, force: bool = False,
                   progress=None, recognizer=None) -> dict:
    """OCR the chart, validate, then atomically replace the reusable catalog.

    Unresolved RGB rows write a candidate/review file and leave the active
    catalog untouched. Corrections are bound to the source image checksum.
    """
    source, destination = Path(source).resolve(),Path(destination).resolve()
    if destination.suffix.lower()!='.json' or source==destination:
        raise ValueError('Palette destination must be a separate .json catalog')
    source_hash=sha256(source)
    if corrections is None:
        saved=destination.with_suffix('.corrections.json')
        if saved.exists():
            previous=json.loads(saved.read_text(encoding='utf-8'))
            # Curated corrections are reused only for the exact same chart.
            corrections=previous if previous.get('source_sha256')==source_hash else {}
    corrections=corrections or {}
    if corrections and corrections.get("source_sha256") != source_hash:
        raise ValueError("Corrections must contain the matching chart source_sha256")
    overrides=corrections.get("entries",{})
    corrections_hash=hashlib.sha256(json.dumps(corrections,sort_keys=True).encode()).hexdigest()
    if destination.exists():
        old=load_palette(destination)
        if not force and old["source_sha256"]==source_hash and old.get("corrections_sha256")==corrections_hash and old.get('importer')==IMPORTER:
            return {"status":"unchanged", "catalog":str(destination), "version":old["version"], "colors":len(old["entries"])}
    if recognizer is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as error:
            raise ValueError('Palette rebuilding requires the palette-update extra: pip install -e ".[palette-update]"') from error
        model=ensure_ocr_model(destination.parent/'.ocr')
        engine=RapidOCR(rec_model_path=str(model),intra_op_num_threads=2,inter_op_num_threads=2,rec_batch_num=24)
        recognizer=lambda crops:engine.text_rec(crops)[0]
    entries=[];issues=[];seen=set()
    with Image.open(source) as original:
        from PIL import ImageCms
        import io
        source_profile=ImageCms.getProfileName(ImageCms.ImageCmsProfile(io.BytesIO(original.info["icc_profile"]))).strip() if original.info.get("icc_profile") else "untagged"
        image=original.convert("RGB")
        columns,rows=detect_grid(image)
        normal_gap=int(np.median([rows[i+1][0]-rows[i][1] for i in range(len(rows)-1)]))
        for row,(_,bottom) in enumerate(rows):
            gap=normal_gap
            crops=[_label(image,a,b,bottom,gap,name) for a,b in columns for name in (False,True)]
            readings=recognizer(crops)
            if len(readings)!=len(crops):
                raise ValueError("OCR returned an incomplete row")
            for col,(a,b) in enumerate(columns):
                identifier=f"r{row+1:02d}c{col+1:02d}";seen.add(identifier)
                rgb_text,rgb_conf=readings[col*2]
                name,name_conf=readings[col*2+1]
                name=' '.join(name.strip().split())
                rgb=parse_rgb(rgb_text)
                correction=overrides.get(identifier,{})
                if correction.keys()-{"rgb","name"}:
                    raise ValueError(f"Unsupported correction for {identifier}")
                rgb=correction.get("rgb",rgb);name=correction.get("name",name)
                reasons=[]
                if rgb is None or len(rgb)!=3 or any(type(v) is not int or not 0<=v<=255 for v in rgb):
                    reasons.append("unresolved_rgb")
                elif rgb_conf<.90 and "rgb" not in correction:
                    reasons.append("low_rgb_confidence")
                if not name: reasons.append("missing_name")
                elif name_conf<.92 and "name" not in correction: reasons.append("check_name")
                if reasons: issues.append({"id":identifier,"reasons":reasons,"rgb_text":rgb_text,"name":name,
                                           "rgb_confidence":round(float(rgb_conf),4),"name_confidence":round(float(name_conf),4)})
                center=((a+b)//2,(rows[row][0]+bottom)//2)
                entries.append({"id":identifier,"name":name,"rgb":rgb,"row":row+1,"column":col+1,
                                "sample_rgb":list(image.getpixel(center)),"name_source":"correction" if "name" in correction else "ocr",
                                "rgb_confidence":round(float(rgb_conf),4),"name_confidence":round(float(name_conf),4)})
            if progress: progress(row+1,len(rows))
    if overrides.keys()-seen:
        raise ValueError(f"Unknown correction IDs: {sorted(overrides.keys()-seen)}")
    if sha256(source)!=source_hash:
        raise ValueError('Chart changed during import; retry with a stable source file')
    catalog={"schema_version":1,"name":"pantonic","color_space":"sRGB","interpretation":"printed_rgb_labels",
             "source_file":source.name,"source_sha256":source_hash,"source_profile":source_profile,
             "corrections_sha256":corrections_hash,"grid":{"rows":len(rows),"columns":len(columns)},
             "importer":IMPORTER,"ocr_model_sha256":OCR_MODEL_SHA256,"entries":entries,
             "name_review_count":sum('check_name' in i['reasons'] for i in issues)}
    blocking=[i for i in issues if any(r!='check_name' for r in i['reasons'])]
    review=destination.with_suffix(".review.json")
    atomic_json(review,{"source_sha256":source_hash,"issues":issues,"blocking_count":len(blocking)})
    if blocking:
        candidate=destination.with_suffix(".candidate.json")
        atomic_json(candidate,catalog)
        return {"status":"needs_corrections","blocking_count":len(blocking),"candidate":str(candidate),
                "review":str(review),"active_palette_changed":False}
    catalog["version"]=version_of(catalog)
    atomic_json(destination,catalog)
    destination.with_suffix(".candidate.json").unlink(missing_ok=True)
    return {"status":"updated","catalog":str(destination),"version":catalog["version"],"colors":len(entries),
            "name_review_count":catalog["name_review_count"],"review":str(review)}


class Matcher:
    """Deterministic nearest-neighbor matching using CIELAB distance (Delta E 76)."""
    def __init__(self,catalog: dict):
        self.catalog=catalog
        self.entries=catalog['entries']
        self.rgb=np.array([e['rgb'] for e in self.entries],dtype=np.uint8)
        self.lab=cv2.cvtColor(self.rgb.astype(np.float32).reshape(1,-1,3)/255,cv2.COLOR_RGB2LAB).reshape(-1,3)

    def indices(self,colors):
        values=np.asarray(colors,dtype=np.uint8).reshape(-1,3)
        labs=cv2.cvtColor(values.astype(np.float32).reshape(1,-1,3)/255,cv2.COLOR_RGB2LAB).reshape(-1,3)
        result=[]
        for start in range(0,len(labs),128):
            distances=((labs[start:start+128,None,:]-self.lab[None,:,:])**2).sum(axis=2)
            result.extend(np.argmin(distances,axis=1).tolist())
        return np.array(result,dtype=int)

    def color(self,color: str):
        rgb=ImageColor.getrgb(color)
        if len(rgb)!=3: raise ValueError("Palette paints must be opaque RGB")
        entry=self.entries[int(self.indices([rgb])[0])]
        return '#%02X%02X%02X'%tuple(entry['rgb']),entry

    def image(self,image: Image.Image) -> Image.Image:
        array=np.array(image.convert('RGB'))
        colors,inverse=np.unique(array.reshape(-1,3),axis=0,return_inverse=True)
        values=self.rgb[self.indices(colors)]
        return Image.fromarray(values[inverse].reshape(array.shape))

    def constrain_svg(self,root) -> list[dict]:
        used={}
        for element in root.iter():
            # Clip paths define geometry, not paints. Our writer uses explicit
            # paint attributes, never CSS styles or opacity-derived colors.
            if element.tag.endswith('clipPath'): continue
            for key in ('fill','stroke','stop-color'):
                color=element.get(key)
                if color is None or color=='none': continue
                value,entry=self.color(color)
                element.set(key,value)
                element.set(f'data-{key}-palette-id',entry['id'])
                used[tuple(entry['rgb'])]=entry
        return sorted(used.values(),key=lambda e:(e['row'],e['column']))


def write_color_report(path: Path,catalog: dict,entries: list[dict],svg_name: str) -> None:
    lines=[f'Vector: {svg_name}',f'Palette: {catalog["name"]}',f'Palette version: {catalog["version"]}',
           f'Source: {catalog["source_file"]}',f'Source SHA256: {catalog["source_sha256"]}',
           'Color interpretation: printed RGB labels, treated as sRGB',
           'Scope: unique paint colors defined in the SVG; raster antialiasing is excluded.',
           'Names were OCR-extracted unless marked as corrected; consult the palette review report.',
           f'Colors used: {len(entries)}','']
    for entry in entries:
        lines.extend([f'{entry["id"]} | {entry["name"]}',
                      'RGB: '+', '.join(map(str,entry['rgb'])),
                      'HEX: #%02X%02X%02X'%tuple(entry['rgb']),
                      'Name source: '+entry.get('name_source','catalog'),''])
    path.write_text('\n'.join(lines),encoding='utf-8')


def build_color_review(folder: Path, clean: Image.Image, masks: dict[str, Image.Image],
                       settings: dict, catalog: dict) -> dict:
    """Propose colors before tracing and save the exact trace input for approval."""
    matcher=Matcher(catalog)
    source=clean.convert('RGB').copy()
    source.thumbnail((settings['trace_max_dimension'],settings['trace_max_dimension']),Image.Resampling.LANCZOS)
    small_masks={name:np.array(mask.resize(source.size,Image.Resampling.NEAREST))>0 for name,mask in masks.items()}
    if any(not mask.any() for mask in small_masks.values()):
        raise ValueError('A panel disappears at analysis resolution; increase trace_max_dimension')
    union=np.logical_or.reduce(list(small_masks.values()))
    matched=np.array(matcher.image(source))
    background,bg_entry=matcher.color(settings['background'])
    matched[~union]=bg_entry['rgb']
    extra={tuple(bg_entry['rgb']):{'entry':bg_entry,'roles':{
        'export_background' if settings['svg']['background']=='solid' else 'tiff_background'}}}
    if settings.get('preserve_white_details',True):
        original=np.array(clean.convert('RGB')).astype(np.int16)
        white=((original.min(2)>=210)&((original.max(2)-original.min(2))<=30)).astype(np.uint8)*255
        white=np.array(Image.fromarray(white).resize(source.size,Image.Resampling.NEAREST))>0
        white &= union
        if white.any():
            _,entry=matcher.color('#ffffff')
            matched[white]=entry['rgb']
            key=tuple(entry['rgb'])
            extra.setdefault(key,{'entry':entry,'roles':set()})['roles'].add('white_details')
    by_rgb={}
    for entry in catalog['entries']:
        by_rgb.setdefault(tuple(entry['rgb']),entry)
    counts={}
    for name,mask in small_masks.items():
        colors,amounts=np.unique(matched[mask],axis=0,return_counts=True)
        for color,count in zip(colors,amounts):
            key=tuple(map(int,color))
            counts.setdefault(key,{'entry':by_rgb[key],'roles':set(),'panel_pixels':{}})
            counts[key]['roles'].add(name)
            counts[key]['panel_pixels'][name]=int(count)
    for key,value in extra.items():
        counts.setdefault(key,{'entry':value['entry'],'roles':set(),'panel_pixels':{}})
        counts[key]['roles'].update(value['roles'])
    total=int(union.sum())
    colors=[]
    for key,value in counts.items():
        entry=value['entry'];pixels=sum(value['panel_pixels'].values())
        colors.append({'id':entry['id'],'name':entry['name'],'rgb':list(key),'hex':'#%02X%02X%02X'%key,
                       'roles':sorted(value['roles']),'panel_pixels':value['panel_pixels'],
                       'panel_percent':round(pixels/total*100,4) if total else 0,
                       'per_panel_percent':{name:round(value['panel_pixels'].get(name,0)/int(mask.sum())*100,4)
                                            for name,mask in small_masks.items()}})
    colors.sort(key=lambda color:(-sum(color['panel_pixels'].values()),color['id']))
    review={'schema_version':1,'palette_version':catalog['version'],'color_space':'sRGB',
            'status':'proposal','approval_required':True,'color_count':len(colors),'colors':colors,
            'analysis_size':list(source.size),'coverage_scope':'Approximate panel pixel share at analysis resolution; excludes the exterior background.',
            'files':{'selection':'color-selection.json','colors_txt':'color-selection.txt',
                     'preview':'palette-matched.png','comparison':'color-comparison.jpg','swatches':'colors-review.html'}}
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    Image.fromarray(matched).save(folder/'palette-matched.png',icc_profile=profile)
    left=source.copy();left.thumbnail((1000,1000))
    right=Image.fromarray(matched).resize(left.size,Image.Resampling.NEAREST)
    comparison=Image.new('RGB',(left.width*2,left.height+32),'white')
    comparison.paste(left,(0,32));comparison.paste(right,(left.width,32))
    draw=ImageDraw.Draw(comparison)
    draw.text((8,8),'RECONSTRUCTION',fill='black')
    draw.text((left.width+8,8),'PROPOSED PALETTE COLORS',fill='black')
    comparison.save(folder/'color-comparison.jpg',quality=92,icc_profile=profile)
    lines=['Proposed panel colors - awaiting artwork AND color approval',
           f'Palette version: {catalog["version"]}',f'Colors selected: {len(colors)}',
           review['coverage_scope'],'']
    cards=[]
    for color in colors:
        lines.extend([f'{color["id"]} | {color["name"]}',
                      'RGB: '+', '.join(map(str,color['rgb'])),f'HEX: {color["hex"]}',
                      f'Panel share: {color["panel_percent"]}% | Roles: {", ".join(color["roles"])}',''])
        cards.append(f'<article><div class="swatch" style="background:{color["hex"]}"></div>'
                     f'<strong>{html.escape(color["name"])}</strong><br>{color["id"]} · {color["hex"]}<br>'
                     f'RGB {", ".join(map(str,color["rgb"]))}<br>{color["panel_percent"]}% of panels<br>'
                     f'<small>{html.escape(", ".join(color["roles"]))}</small></article>')
    (folder/'color-selection.txt').write_text('\n'.join(lines),encoding='utf-8')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Artwork and color approval</title><style>body{font:16px/1.5 system-ui;margin:32px;background:#f4f5f7;color:#182336}img{max-width:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}article{background:white;padding:16px;border-radius:10px}.swatch{height:72px;border:1px solid #aaa;margin-bottom:8px}small{color:#536273}</style>
<h1>Review the panels and selected colors</h1><p>Approve the artwork, panel masks and this color selection together. Approval is recorded in the job; this page is a static review record.</p>
<img src="color-comparison.jpg" alt="Original reconstruction versus palette-matched panels">
<p>Left: reconstructed artwork. Right: proposed colors. Pixel shares are approximate, measured inside the panels; background and white-detail roles are identified separately. Vectorization may simplify shapes or omit colors, but may not add unapproved palette colors.</p>
<p><a href="palette-matched.png">Palette preview</a> · <a href="color-selection.txt">Color list</a> · <a href="mask-review.png">Panel mask review</a></p><div class="grid">'''+''.join(cards)+'</div></html>'
    (folder/'colors-review.html').write_text(page,encoding='utf-8')
    atomic_json(folder/'color-selection.json',review)
    return review
