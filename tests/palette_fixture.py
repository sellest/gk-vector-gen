from pathlib import Path

from gk_vector.palette import atomic_json, version_of


def make_palette(path: Path) -> Path:
    colors=[('Navy',[0,48,112]),('White',[255,255,255]),('Background',[230,230,230]),
            ('Red',[230,10,20]),('Cyan',[0,180,240]),('Black',[0,0,0])]
    data={'schema_version':1,'name':'test-palette','color_space':'sRGB',
          'source_file':'fixture.tif','source_sha256':'0'*64,'grid':{'rows':1,'columns':len(colors)},
          'name_review_count':0,'entries':[{'id':f'r01c{i+1:02d}','name':name,'rgb':rgb,
                                         'row':1,'column':i+1,'name_source':'correction'}
                                        for i,(name,rgb) in enumerate(colors)]}
    data['version']=version_of(data)
    atomic_json(path,data)
    return path
