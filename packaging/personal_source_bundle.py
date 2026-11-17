"""Bundle the committed personal edition and its native corresponding source."""
import io
import subprocess
import sys
import zipfile

from verify_native import ROOT, verify_inputs


def main():
    manifest = verify_inputs()
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT).strip():
        raise SystemExit('Commit tracked changes before making the release source bundle')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    sys.path.insert(0, str(ROOT))
    from goggles_bridge import __version__
    dist = ROOT/'dist'
    dist.mkdir(exist_ok=True)
    output = dist/f'GogglesBridgePersonal-{__version__}-Source.zip'
    archive = subprocess.check_output(['git', 'archive', '--format=zip', commit], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as tracked, \
         zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for item in tracked.infolist():
            bundle.writestr(item, tracked.read(item))
        source = manifest['upstream']['source_archive']['path']
        bundle.write(ROOT/source, source)
        bundle.writestr('RELEASE-COMMIT.txt', commit+'\n')
    print(output)


if __name__ == '__main__':
    main()
