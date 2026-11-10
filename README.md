# FreeCAD Manual Downloader Script

This is a modified, working version of the download script originally found on the FreeCAD Wiki.
The original script had broken dependencies and some outdated/incompatible code; this version fixes those issues.

Downloads the FreeCAD User Manual from <https://wiki.freecad.org/FreeCAD_Manual_Converter> and builds an
offline copy:

- **PDF**: cover, clickable table of contents with page numbers, bookmarks
- **EPUB**: cover, table of contents, images

It follows the manual's "next page" links starting at `Manual:Introduction`,
so the chapters come out in reading order.

> The manual's text and images belong to the FreeCAD community and are available
> under Creative Commons Attribution (CC-BY) unless otherwise noted on the wiki.
> The generated PDF/EPUB cover carries an attribution line. If you share the
> files, keep it, and check the wiki for the exact licence version and any
> page or image with different terms.

## Quick start

```bash
python3 freecad_manual_converter.py --max-chapters 3   # quick test (3 pages)
python3 freecad_manual_converter.py                    # full manual
```

Output (in the current folder): `FreeCAD_User_Manual.pdf` and `FreeCAD_User_Manual.epub`.

Options: `--no-epub`, `--no-pdf`, `--pdf NAME`, `--epub NAME`,
`--delay SECONDS` (pause between requests, default 0.3),
`--contact you@example.com` (added to the User-Agent so wiki admins can reach you).

## Installation

Python 3.9 or newer. The libraries are listed in `requirements.txt`.
WeasyPrint also needs the Pango text library installed on your system.

### Fedora

```bash
sudo dnf install python3-pip pango cairo gdk-pixbuf2 dejavu-sans-fonts dejavu-sans-mono-fonts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3-venv python3-pip libpango-1.0-0 libpangoft2-1.0-0 \
                 libcairo2 libgdk-pixbuf-2.0-0 fonts-dejavu
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

WeasyPrint needs the Pango library, which Windows does not include.
(Check the official guide too, as the steps can change:
<https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>)

1. Install Python from <https://www.python.org/downloads/> and tick
   **"Add python.exe to PATH"**.
2. Install MSYS2 from <https://www.msys2.org/>. Open the **MSYS2 MSYS** terminal and run:
   ```
   pacman -S mingw-w64-x86_64-pango
   ```
3. Tell Python where those libraries are. In PowerShell:
   ```powershell
   setx WEASYPRINT_DLL_DIRECTORIES "C:\msys64\mingw64\bin"
   ```
   Then **close and reopen PowerShell**.
4. In the folder with the script:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   py freecad_manual_converter.py --max-chapters 3
   ```

**SVG images on Windows:** CairoSVG needs the Cairo library. If it cannot load,
the script still works and just skips SVG images (it prints a warning). To
include them, install Cairo in MSYS2 as well (`pacman -S mingw-w64-x86_64-cairo`).

## Troubleshooting

- **`OSError: cannot load library 'libpango-1.0-0'`**: Pango is missing or Python
  cannot find it (see the Windows step 3).
- **"no docnav found - stopping crawl here"**: the wiki's navigation markup
  changed; please open an issue with the console output.
- **Slow or interrupted**: re-run; pages are fetched with retries. Raise
  `--delay` if the wiki is slow.

## Contributing

Issues and pull requests are welcome, especially Windows/macOS testing notes.

## Licence

- **Script:** MIT (see `LICENSE`). This repository contains no wiki content.
- **Generated PDF/EPUB:** they contain FreeCAD Wiki content, available under
  Creative Commons Attribution (CC-BY) unless otherwise noted. Credit the source
  (<https://wiki.freecad.org>) and link the licence when sharing them. The script
  cannot detect pages or images that carry different terms.
- **The original wiki content is licensed under the CC BY 3.0.** Accordingly, this
  modified script is also shared under the CC BY 3.0 licence.
