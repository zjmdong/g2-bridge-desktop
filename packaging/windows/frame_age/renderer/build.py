"""Compile the research source only; never opens a renderer window."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
parser=argparse.ArgumentParser(description=__doc__)
pinned=ROOT/'work/toolchain/msys64/ucrt64/bin/g++.exe'
parser.add_argument('--compiler',type=Path,default=pinned if pinned.exists() else shutil.which('g++'))
parser.add_argument('--output',type=Path,default=ROOT/'work/frame-age-renderer/native_pattern.exe')
args=parser.parse_args()
if args.compiler is None or not args.compiler.exists():parser.error('Provide an MSYS2 UCRT64 compiler with --compiler')
compiler=args.compiler.resolve()
output=args.output.resolve()
output.parent.mkdir(parents=True,exist_ok=True)
environment=dict(os.environ)
environment['PATH']=str(compiler.parent)+os.pathsep+environment.get('PATH','')
command=[str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-municode','-static',
    '-DUNICODE','-D_UNICODE','-D_WIN32_WINNT=0x0A00',str(HERE/'native_pattern.cpp'),
    '-o',str(output),'-ld3d11','-ldxgi','-ld3dcompiler','-lgdi32','-luser32','-luuid']
raise SystemExit(subprocess.run(command,env=environment,cwd=HERE).returncode)
