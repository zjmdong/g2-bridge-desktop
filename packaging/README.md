# Package the desktop app

For personal Windows releases, follow [the personal release guide](../docs/PERSONAL-RELEASE.md)
and pass `--native`. The upstream platform build notes below are retained as reference.

The app is a pywebview window over the stream engine. Its code is in `goggles_bridge/app/`, and its interface is plain HTML, CSS, and JavaScript in `goggles_bridge/app/ui/`.

## Build on Windows

Install the app's dependencies, PyInstaller, and [Inno Setup 6](https://jrsoftware.org/isdl.php). Then run the build script from the repository root:

```powershell
python -m pip install -r requirements-app.txt pyinstaller==6.22.3
python packaging/build_windows.py
```

The script writes the app folder to `dist/Goggles Bridge Personal/` and the installer to `dist/GogglesBridgePersonal-VERSION-Setup.exe`. Inno Setup is required: it also builds the optional machine-wide display driver component, `dist/GogglesBridgeDisplay-Setup.exe`. Add its compiler (`ISCC.exe`) to PATH when installed outside the standard location.

The build checks that its Python environment can import the app dependencies and pywebview's window API before downloading or packaging files. Use the same Python interpreter to install dependencies and build the app.

The build downloads a pinned FFmpeg build and checks its SHA-256. That build repeats frames when the screen is still. FFmpeg 9.0 and earlier don't.

To check that a built app starts, run it with `--self-test`. It opens a hidden window, waits for the interface to draw, and exits with code 0.

## Build on macOS

On a Mac with Apple silicon, install the app's dependencies, PyInstaller, and Apple's command-line developer tools. Then run the build script:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-app.txt pyinstaller==6.22.3
.venv/bin/python packaging/build_macos.py
```

The script writes `dist/Goggles Bridge.app` and `dist/GogglesBridge-VERSION.dmg`. The app runs on macOS 12.3 and later. Build it with Python from python.org. With Homebrew's Python, the app runs only on the macOS version of the Mac that built it. The app captures and encodes with the ScreenCaptureKit helper, so it doesn't include FFmpeg. The build compiles the helper and a pinned libusb release for macOS 12.3.

The script signs with the first Developer ID Application certificate in the keychain. To pick another, set `GOGGLES_SIGNING_IDENTITY`. Without a certificate, the app is signed ad hoc, and macOS asks for screen recording permission again after each build. To notarize the disk image, set `GOGGLES_NOTARY_PROFILE` to a `notarytool` keychain profile.

To check the built app, run `"dist/Goggles Bridge.app/Contents/MacOS/Goggles Bridge" --self-test`.

## Preview the interface

Open `goggles_bridge/app/ui/index.html` in a browser. Opened as a file, the interface runs on simulated data. To hold one state, add `?state=streaming`, `waiting`, `unplugged`, `nodriver`, `noscreen`, or `error`. To see the Mac window, add `&mac`.

## Release

1. On GitHub, go to **Actions > Release**, and then select **Run workflow**.
2. Enter the version, and then select **Run workflow**. The workflow opens a pull request titled `chore(release): VERSION`.
3. Merge that pull request. The merge starts the build.
4. Under **Releases**, open the draft. Write the headline and the **What's Changed** entries, and then select **Publish release**.

The app updates only to a release that isn't a pre-release. To publish an update, clear **Set as a pre-release** before you select **Publish release**.

To open the pull request, the workflow needs **Allow GitHub Actions to create and approve pull requests** turned on under **Settings > Actions > General**. If GitHub Actions is on the bypass list of the ruleset for `main`, the workflow also merges the pull request and starts the build.

The build runs when a change to `__version__` in `goggles_bridge/__init__.py` reaches `main`. It builds the Windows installer and the Mac disk image for that version, and attaches both to a draft pre-release. To build the version that the code already has, for example after a failed build, run the workflow again with that version. It fills in their SHA-256 hashes and the pull requests merged since the last release from `.github/RELEASE_TEMPLATE.md`. Publishing the draft creates the version tag.

To sign and notarize the Mac app, the workflow reads these repository secrets:

- `MACOS_CERTIFICATE`: the Developer ID Application certificate and its private key, exported as a `.p12` file and Base64-encoded.
- `MACOS_CERTIFICATE_PASSWORD`: the password of the `.p12` file.
- `NOTARY_KEY`: the contents of an App Store Connect API key file (`.p8`) with the Developer role.
- `NOTARY_KEY_ID` and `NOTARY_ISSUER_ID`: that key's ID and issuer ID.
