# Native Windows FFmpeg build

`manifest.json` pins FFmpeg n9.0.2, the patch, MSYS2 UCRT64 dependencies and the
validated executable. The patch provides DDA timing, a raw-frame mailbox,
D3D11 scaling, asynchronous NVENC and capture-clock delivery. No USB protocol
changes or virtual-display management are included.

Use the manifest's GCC 16.2.0, NASM 3.02 and ffnvcodec 13.0.19.0 packages.
Create the corresponding upstream archive from the official repository:

```sh
git clone --depth 1 --branch n9.0.2 https://github.com/FFmpeg/FFmpeg.git ffmpeg-upstream
git -C ffmpeg-upstream rev-parse HEAD
git -C ffmpeg-upstream archive --format=tar.gz --prefix=ffmpeg-n9.0.2/ \
    -o ../ffmpeg-upstream-n9.0.2.tar.gz n9.0.2
```

Check its commit and SHA-256 against the manifest. Put the archive at
`vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz`. Git/compressor versions
can change archive bytes; use the matching source bundle if necessary.
From an MSYS2 UCRT64 shell at the repository root, run:

```sh
bash packaging/windows/ffmpeg/build.sh
```

Output is `work/ffmpeg-repro-n9.0.2/install/bin/ffmpeg.exe`. Optional variables
are `GOGGLES_FFMPEG_WORK`, `GOGGLES_FFMPEG_OUTPUT`, `GOGGLES_FFMPEG_SOURCE_TAR`
and `GOGGLES_FFMPEG_JOBS`. Use MSYS paths without spaces. `--prepare-only`
verifies and applies the patch without compiling. Changed inputs require a
fresh work directory. The script does not modify vendor binaries.

Copy the executable to `vendor/ffmpeg/ffmpeg.exe`, then run
`python packaging/verify_native.py`. To update the patch, edit a checkout of
the pinned commit, export its diff (including new headers), rebuild and
validate before updating the manifest's patch, recipe and binary records.
Do not assign an old executable to changed source inputs.

Distribute `NOTICE.txt`, `licenses/`, the manifest, build recipe, patch and
complete upstream source archive with the native executable. Fixed timestamps
and remapped source paths help reproducibility; verify clean-build hashes
before claiming identical output. Hardware validation follows
[the native backend guide](../../../docs/WINDOWS-NATIVE-CAPTURE.md).
