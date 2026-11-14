"""Explicitly compile a synthetic source fixture; never launch it or change displays."""
import argparse
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=('extended','primary'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--compiler',type=Path,
        default=ROOT/'work/toolchain/msys64/ucrt64/bin/g++.exe')
    args = parser.parse_args()
    compiler = args.compiler.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        parser.error('Choose a new output executable; existing builds are not overwritten')
    output.parent.mkdir(parents=True,exist_ok=True)
    source = HERE/f'renderer-{args.source}-latency2.cpp'
    environment = dict(os.environ)
    environment['PATH'] = str(compiler.parent)+os.pathsep+environment.get('PATH','')
    command = [str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-municode','-static',
        '-DUNICODE','-D_UNICODE','-D_WIN32_WINNT=0x0A00',str(source),'-o',str(output),
        '-ld3d11','-ldxgi','-ld3dcompiler','-lgdi32','-luser32','-luuid']
    return subprocess.run(command,env=environment,cwd=HERE).returncode


if __name__=='__main__':
    raise SystemExit(main())
