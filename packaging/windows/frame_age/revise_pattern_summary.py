"""Recompute bounded identity windows from already saved numeric marker data.

No recapture or video decode; original immutable evidence stays untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path
from pattern_identity import summarize_markers


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    original=args.input.read_bytes()
    data=json.loads(original)
    identity=data['pattern_identity']
    if identity['status']!='completed':p.error('Only valid decoded marker records can be re-summarized')
    end=data['start_qpc']+int(data['seconds']*data['frequency'])
    identity.update(summarize_markers(identity['records'],data['frequency'],end))
    if identity['measured_frames']!=data['measured_frames']:p.error('Identity and host windows still differ')
    data['analysis_revision']=dict(version=2,reason='Exclude graceful-stop tail from identity summary, matching host measurement window',
        original_file=str(args.input.resolve()),original_sha256=hashlib.sha256(original).hexdigest(),
        new_capture=False,new_decode=False,window_end_qpc=end)
    with args.output.open('x',encoding='utf-8') as file:json.dump(data,file,indent=2);file.write('\n')
    print(json.dumps({k:v for k,v in identity.items() if k!='records'},indent=2))


if __name__=='__main__':main()
