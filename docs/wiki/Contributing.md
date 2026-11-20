# Contributing, Translations, and Vendor Database

Contributions are welcome: bug reports, code, translations, vendor data and documentation. SynetScan is licensed under the **GNU GPL v3 or later**. By contributing, you agree that your contribution is distributed under the same license.

## Ways to contribute

- **Report bugs and ideas** in the [issues](https://github.com/philiphohn/synetscan/issues). See [Reporting Bugs and Requesting Features](Reporting-Bugs).
- **Test on other hardware**, especially ARM models and other DSM versions, and report the result.
- **Improve the device recognition**: a report with a device's vendor, ports, services and names helps make the classification rules better.
- **Code, translations, documentation**: pull requests against the main repository.

## Pull requests

1. Fork [philiphohn/synetscan](https://github.com/philiphohn/synetscan) and create a branch.
2. Make your change. Keep each pull request to one topic.
3. Run the tests: `python3 -m unittest discover -s tests`. Add tests for new behaviour in `tests/`.
4. Try the change in the [local preview](Local-Development). Follow the safety notes there before running the daemon on a machine outside your own network.
5. Describe what you changed and why, and how you tested it, ideally on a real NAS.

## Code guidelines

- **Python standard library only.** No third-party modules: the package must run with the Python that DSM ships.
- **Python 3.6 compatible**, tested with 3.8 (DSM 7) and 3.12. No syntax or library features newer than 3.6 in `src/`.
- **No root, no compiled code.** Everything must work as the unprivileged package user and stay `noarch`.
- **Treat everything from the network as hostile.** Clean text with `util.clean_text`, bound sizes and counts, set time limits, and never resolve names or follow links to other hosts. `tests/test_security.py` shows the expectations.
- **No shell commands built from input.** Use argument lists with `subprocess`.
- **The UI has no build step**: plain JavaScript, HTML and CSS in `src/ui/`. Insert text from the network only escaped (`esc()`). The Content Security Policy forbids inline scripts.
- Keep the DSM look: follow the existing styles in `src/ui/css/dsm.css`.

## Translations

The interface texts are in `src/ui/js/i18n.js`, with one block per language (`en`, `de`). Keys missing in a language fall back to English.

**Improving an existing translation:** edit the values in `i18n.js`. Keep placeholders such as `{0}` and `{1}`.

**Adding a language** takes a little more:

1. Add a block for the language to `window.SS_I18N` in `src/ui/js/i18n.js`, with the same keys as `en`.
2. Extend `detectLang()` in `src/ui/js/app.js`. It currently recognises only German (DSM's language code `ger`, or `de…`) and uses English otherwise. DSM reports its own language codes such as `enu` or `ger` **(check the code your DSM language uses)**.
3. Optionally add the Package Center description in that language to `spk/INFO.in` (as `description_<code>`, like `description_ger`) **(to verify: supported codes)**.
4. Check the layout in the preview. Some languages need more room in buttons and columns.

Labels used in this wiki are the English ones, with the German label in brackets where it helps.

## Vendor database

The MAC vendor names come from the IEEE registry as published by the Wireshark project. SynetScan bundles a compact version in `src/share/oui.txt.gz` (about 59,000 entries, longest-prefix match for MA-L, MA-M and MA-S blocks).

To update it:

```sh
curl -o third_party/manuf https://www.wireshark.org/download/automated/data/manuf
python3 tools/build_oui.py third_party/manuf src/share/oui.txt.gz
python3 -m unittest discover -s tests
```

`build_oui.py` shortens vendor names (it drops suffixes such as *Inc.*, *GmbH*, *Co., Ltd.*). All-lowercase registry names are capitalised when they are displayed. Commit both files in a pull request of its own.

## Documentation and this wiki

**The canonical source of this wiki is `docs/wiki/` in the main repository.** The GitHub wiki is published from there automatically, so edits made directly in the GitHub wiki are overwritten. To change a page:

1. Edit the Markdown file in `docs/wiki/` (file name = page name, e.g. `Scan-Targets.md`).
2. Link to other pages wiki-style, without `.md`: `[Scan Targets](Scan-Targets)`. Reference images as `images/<file>.png`.
3. Practical guides follow the pattern: *What you will achieve · Prerequisites · Steps · Expected result · Common problems · Related articles*. Troubleshooting entries follow *symptom → likely explanation → checks → resolution → what to include in a bug report*.
4. Ground statements in the code. Mark behaviour added after the latest release with *Available since x.y.z*. Mark DSM steps you couldn't verify as **(to verify)**.
5. **Use only made-up data in screenshots**: the demo devices from `tools/demo/seed.py`, addresses like 192.168.1.x, 10.0.0.x and 2001:db8::, invented MAC addresses and names. Never show a real network. Regenerate the app screenshots with `tools/demo/wiki_shots.mjs` (see [Local Development](Local-Development#screenshots-and-recordings)). Screens of DSM itself (Package Center, Control Panel) must be real captures from a NAS, with private details removed.
6. Open a pull request.

`_Sidebar.md` and `_Footer.md` are the wiki's navigation. Add new pages to the index page of their section, and to `Home.md`.

## Related articles

- [Local Development and Testing](Local-Development)
- [Building Packages and Publishing Releases](Building-and-Releasing)
- [Architecture and DSM Integration](Architecture)
- [Reporting Bugs and Requesting Features](Reporting-Bugs)
