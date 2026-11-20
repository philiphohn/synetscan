# Building Packages and Publishing Releases

## Building the package

```sh
./build.sh                 # dist/SynetScan-<version>-0001-noarch.spk
BUILD=0002 ./build.sh      # dist/SynetScan-<version>-0002-noarch.spk
```

Requirements: a POSIX shell, `tar`, `md5sum`, `sed` and Python 3. Pillow is only needed if the icons have to be generated.

What `build.sh` does:

1. Reads the version from `__version__` in `src/lib/synetscan/__init__.py` and appends the build number (`BUILD`, default `0001`): for example `1.1.5-0001`.
2. Generates `src/share/oui.txt.gz` from `third_party/manuf` if it's missing (`tools/build_oui.py`), and the icons if they're missing (`tools/make_icons.py`, needs Pillow).
3. Builds `package.tgz` from `src/bin`, `src/lib`, `src/share` and `src/ui`, plus `LICENSE`. It removes `__pycache__` and `.pyc` files, sets modes 755/644 (755 for `synetscand` and `api.cgi`), and stores everything owned by root (uid 0).
4. Fills in `spk/INFO.in`: version, creation time and the MD5 checksum of `package.tgz`.
5. Packs `INFO`, `package.tgz`, `scripts/`, `conf/` and the two package icons into `dist/SynetScan-<version>-<build>-noarch.spk`, a plain tar file.

The license is included in the installed files, not at the top level of the `.spk`. At the top level, DSM would show it as an agreement step, and the GPL needs no acceptance to use the software.

## Version numbers

The version appears in several files. Change all of them together:

| File | Where |
| --- | --- |
| `src/lib/synetscan/__init__.py` | `__version__ = "x.y.z"`: used by `build.sh` for INFO and the file name, and reported by the service |
| `src/ui/config` | `"version": "x.y.z"` of the app entry |
| `src/ui/synetscan.js` | `var VERSION = "x.y.z"`: cache-busting suffix for `index.html` |
| `src/ui/index.html` | `?v=x.y.z` on the CSS and the three scripts: cache busting |

If the UI files keep an old version, browsers and the DSM desktop may keep serving old files after an update. The build number (`BUILD`) distinguishes rebuilds of the same version. DSM compares the full version `x.y.z-build` when deciding whether a package is an update **(to verify)**.

## Release checklist

1. **Tests pass**: `python3 -m unittest discover -s tests`.
2. **Version** bumped in all four places (see above).
3. **Vendor database** current, if wanted: see [Contributing](Contributing#vendor-database).
4. **Build**: `./build.sh`.
5. **Test on a real NAS**: fresh install, and update over the previous release (data must survive), on DSM 7.1 and 7.2+ if possible. Open the app locally and over QuickConnect, run a scan, and check the log. See [Local Development](Local-Development#checking-a-change-on-a-real-nas).
6. **README** and this **wiki** updated for new or changed behaviour. Mark new behaviour with *Available since x.y.z*.
7. **Commit and tag**: `git tag vx.y.z`. Earlier tags: `v1.0.3`, `v1.0.4`, `v1.1.2`.
8. **GitHub release**: create a release for the tag, attach `dist/SynetScan-x.y.z-0001-noarch.spk`, and write the release notes. For example with the GitHub CLI:

   ```sh
   gh release create vx.y.z dist/SynetScan-x.y.z-0001-noarch.spk \
     --title "SynetScan x.y.z" --notes-file release-notes.md
   ```

**Release notes live in GitHub Releases**, not in this wiki: [github.com/philiphohn/synetscan/releases](https://github.com/philiphohn/synetscan/releases). Write them for users: what's new, what's fixed, anything to do after updating (reload DSM, for example), and known issues.

The README's download link points to `releases/latest`, so it picks up the new release automatically.

## Related articles

- [Local Development and Testing](Local-Development)
- [Architecture and DSM Integration](Architecture)
- [Contributing](Contributing)
