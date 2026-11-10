#!/usr/bin/env python3
# ==============================================================================
# FreeCAD Manual Downloader Script (Modified/Working Version)
# 
# Original concept and code sourced from the FreeCAD Wiki (https://wiki.freecad.org/FreeCAD_Manual_Converter)
# Original Wiki content licensed under CC BY 3.0.
# 
# Modified by: Orkeven
# Changes made: Fixed broken dependencies and updated library calls.
# Needed to make it work on Fedora, hence this script.
# ==============================================================================

import argparse
import base64
import hashlib
import re
import sys
import time
import uuid
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont
from weasyprint import HTML

# CairoSVG is optional: it needs the Cairo library, which is awkward on Windows.
# Without it the script still works; SVG images are simply skipped.
try:
    import cairosvg
except (ImportError, OSError):
    cairosvg = None

BASE = "https://wiki.freecad.org"
API = BASE + "/api.php"
START_PAGE = BASE + "/Manual:Introduction"
MAX_IMG_WIDTH = 800
ATTRIBUTION = ("Content from the FreeCAD Wiki (https://wiki.freecad.org), "
               "available under Creative Commons Attribution (CC-BY) "
               "unless otherwise noted. Converted to PDF/EPUB; no content changes.")

FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",   # Fedora
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     # Debian/Ubuntu
    "C:/Windows/Fonts/arialbd.ttf",                             # Windows
    "C:/Windows/Fonts/segoeuib.ttf",
    "/Library/Fonts/Arial Bold.ttf",                            # macOS
]

PDF_CSS = """
@page {
    size: A4;
    margin: 2cm 1.8cm;
    @bottom-center { content: counter(page); font-size: 9pt; color: #666; }
}
@page cover { @bottom-center { content: none; } }
body { font-family: "DejaVu Sans", "Liberation Sans", Arial, "Segoe UI", sans-serif;
       font-size: 10.5pt; line-height: 1.45; }
.cover { page: cover; text-align: center; padding-top: 7cm; break-after: page; }
.cover h1 { font-size: 36pt; margin: 0; }
.cover p { color: #666; font-size: 14pt; }
.cover p.attrib { font-size: 9pt; margin-top: 4cm; }
.toc h1 { text-align: center; }
.toc ol { list-style: none; padding: 0; }
.toc li { margin: 4px 0; }
.toc a { color: #000; text-decoration: none; }
.toc a::after { content: leader('.') target-counter(attr(href), page); }
section.chapter { break-before: page; }
section.chapter > div > h1:first-child { text-align: center; font-size: 22pt; }
h2 { font-size: 16pt; margin-top: 1.2em; }
h3 { font-size: 13pt; }
h1, h2, h3, h4 { break-after: avoid; }
img { max-width: 100%; height: auto; }
figure, .thumb { break-inside: avoid; margin: 1em 0; }
a { color: #0645ad; text-decoration: none; }
pre { font-family: "DejaVu Sans Mono", Consolas, "Courier New", monospace; font-size: 9pt;
      background: #f4f4f4; padding: 8px; white-space: pre-wrap;
      word-wrap: break-word; border: 1px solid #ddd; border-radius: 4px; }
code { font-family: "DejaVu Sans Mono", Consolas, "Courier New", monospace; font-size: 9.5pt;
       background: #f4f4f4; padding: 0 3px; }
pre code { background: none; padding: 0; }
table.wikitable { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 9.5pt; }
.wikitable th, .wikitable td { border: 1px solid #ccc; padding: 6px; }
.wikitable th { background: #f2f2f2; }
.wikitable tr { break-inside: avoid; }
"""

EPUB_CSS = """
body { margin: 1em; font-family: sans-serif; }
h1 { text-align: center; }
img { max-width: 100%; height: auto; }
pre { background: #f4f4f4; padding: 0.5em; white-space: pre-wrap; border: 1px solid #ddd; }
code { font-family: monospace; background: #f4f4f4; }
table { width: 100%; border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #ccc; padding: 0.4em; }
"""


class FreeCADManualConverter:
    def __init__(self, delay=0.3, max_chapters=None, contact=None):
        self.session = requests.Session()
        agent = "FreeCAD-Manual-Converter/2.1 (offline copy; MediaWiki API client"
        agent += f"; contact: {contact})" if contact else ")"
        self.session.headers.update({"User-Agent": agent})
        self.warned_svg = False
        self.delay = delay
        self.max_chapters = max_chapters
        self.chapters = []       # dicts: number, title, id, html
        self.image_cache = {}    # image url -> (bytes, mime) or None

    # ------------------------------------------------------------------ utils
    @staticmethod
    def page_key(url_or_title):
        """Normalise a URL or title to e.g. 'Manual:Introduction'."""
        s = url_or_title
        if s.startswith("http") or s.startswith("/"):
            p = urlparse(s)
            if p.path.endswith("index.php"):
                s = parse_qs(p.query).get("title", [""])[0]
            else:
                s = p.path
        return unquote(s).lstrip("/").replace(" ", "_")

    @staticmethod
    def slugify(text):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")

    def get(self, url, **kwargs):
        last_error = None
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=30, **kwargs)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last_error = e
                time.sleep(1.5 * (attempt + 1))
        raise last_error

    # ----------------------------------------------------------------- images
    def get_image(self, img_url, declared_width=None):
        """Return (bytes, mime) for an image, resized/optimised. Cached."""
        if img_url in self.image_cache:
            return self.image_cache[img_url]
        result = None
        try:
            is_svg = urlparse(img_url).path.lower().endswith(".svg")
            if is_svg and cairosvg is None:
                if not self.warned_svg:
                    print("  ! CairoSVG not available: SVG images will be skipped")
                    self.warned_svg = True
                self.image_cache[img_url] = None
                return None
            r = self.get(img_url)
            if is_svg:
                width = min(declared_width or MAX_IMG_WIDTH, MAX_IMG_WIDTH)
                result = (cairosvg.svg2png(bytestring=r.content, output_width=width),
                          "image/png")
            else:
                img = Image.open(BytesIO(r.content))
                img.load()
                if img.width > MAX_IMG_WIDTH:
                    h = int(img.height * MAX_IMG_WIDTH / img.width)
                    img = img.resize((MAX_IMG_WIDTH, h), Image.Resampling.LANCZOS)
                buf = BytesIO()
                if img.mode in ("RGBA", "LA", "P"):
                    img.convert("RGBA").save(buf, format="PNG", optimize=True)
                    result = (buf.getvalue(), "image/png")
                else:
                    img.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
                    result = (buf.getvalue(), "image/jpeg")
        except Exception as e:
            print(f"  ! image skipped {img_url}: {e}")
        self.image_cache[img_url] = result
        return result

    # ------------------------------------------------------------- fetching
    def fetch_page(self, title):
        """Fetch rendered HTML for a wiki page through the MediaWiki API."""
        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",          # let the server follow redirects
        }
        try:
            data = self.get(API, params=params).json()
        except Exception as e:
            print(f"  ! error fetching {title}: {e}")
            return None
        if "error" in data:
            print(f"  ! API error for {title}: {data['error'].get('info', data['error'])}")
            return None
        return {"title": data["parse"]["title"], "html": data["parse"]["text"]}

    def find_next_page(self, html, visited):
        """
        Return the next manual page found in the docnav bar, or None.
        Works by picking the first Manual: link that has not been visited yet,
        so it does not depend on the order of the prev/start/next links.
        """
        soup = BeautifulSoup(html, "html.parser")
        nav = soup.find(class_="docnav")
        if nav is None:
            print("  ! no docnav found - stopping crawl here")
            return None
        for a in nav.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if "start" in text or "table of contents" in text:
                continue
            key = self.page_key(a["href"])
            if not key.startswith("Manual:"):
                continue
            if re.search(r"/[a-z]{2,3}(-[a-z]+)?$", key):   # translated subpage
                continue
            if key in visited:
                continue
            return key
        return None

    # ------------------------------------------------------------ extraction
    def extract_main_content(self, html, chapter_title, chapter_id):
        soup = BeautifulSoup(html, "html.parser")
        for el in soup.select(".mw-pt-languages, .docnav, .NavFrame, .manualtoc, "
                              ".mw-editsection, script, style, .noprint"):
            el.decompose()

        content = soup.find("div", class_="mw-parser-output") or soup
        h1 = soup.new_tag("h1", id=chapter_id)
        h1.string = chapter_title
        content.insert(0, h1)

        for img in content.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            img_url = urljoin(BASE + "/", src)
            try:
                width = int(img.get("width", ""))
            except ValueError:
                width = None
            got = self.get_image(img_url, width)
            for attr in ("srcset", "loading", "decoding", "data-file-width",
                         "data-file-height"):
                img.attrs.pop(attr, None)
            if got:
                data, mime = got
                img["src"] = f"data:{mime};base64,{base64.b64encode(data).decode()}"
            else:
                img.decompose()

        for a in content.find_all("a", href=True):
            a["href"] = urljoin(BASE + "/", a["href"])
        return str(content)

    # --------------------------------------------------------------- crawling
    def crawl(self, start_page=START_PAGE):
        visited = set()
        key = self.page_key(start_page)
        while key and key not in visited:
            if self.max_chapters and len(self.chapters) >= self.max_chapters:
                break
            visited.add(key)
            number = len(self.chapters) + 1
            print(f"[{number}] {key}")
            page = self.fetch_page(key)
            if not page:
                break
            visited.add(self.page_key(page["title"]))   # in case of redirects

            title = page["title"].replace("Manual:", "").strip()
            chapter_id = f"ch{number}_{self.slugify(title)}"
            next_key = self.find_next_page(page["html"], visited)
            body = self.extract_main_content(page["html"], title, chapter_id)
            self.chapters.append({
                "number": number, "title": title, "id": chapter_id,
                "html": body, "keys": {key, self.page_key(page["title"])},
            })
            key = next_key
            time.sleep(self.delay)
        print(f"Collected {len(self.chapters)} chapters, {len(self.image_cache)} images.")

    # ---------------------------------------------------------------- outputs
    def _localise_links(self, html, make_href):
        """Point links to other chapters of this book at the local chapter."""
        key_to_chapter = {k: c for c in self.chapters for k in c["keys"]}
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(BASE):
                chapter = key_to_chapter.get(self.page_key(href))
                if chapter:
                    a["href"] = make_href(chapter, urlparse(href).fragment)
        return str(soup)

    def build_pdf(self, output_file):
        print(f"Building PDF {output_file} (this can take a minute)...")
        date = datetime.now().strftime("%Y-%m-%d")
        toc = "".join(
            f'<li><a href="#{c["id"]}">{c["number"]}. {c["title"]}</a></li>'
            for c in self.chapters
        )
        sections = "".join(
            f'<section class="chapter" id="sec_{c["id"]}">'
            f'{self._localise_links(c["html"], lambda ch, frag: "#" + ch["id"])}'
            f'</section>'
            for c in self.chapters
        )
        doc = (
            f'<html><head><meta charset="utf-8"><title>FreeCAD User Manual</title>'
            f'<style>{PDF_CSS}</style></head><body>'
            f'<div class="cover"><h1>FreeCAD<br>User Manual</h1><p>{date}</p>'
            f'<p class="attrib">{ATTRIBUTION}</p></div>'
            f'<div class="toc"><h1>Table of Contents</h1><ol>{toc}</ol></div>'
            f'{sections}</body></html>'
        )
        HTML(string=doc, base_url=BASE).write_pdf(output_file)
        print(f"Created {output_file}")

    def generate_cover(self):
        """Simple cover image (JPEG bytes) for the EPUB."""
        def load_font(size):
            for path in FONT_CANDIDATES:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
            try:
                return ImageFont.load_default(size=size)   # Pillow >= 10.1
            except TypeError:
                return ImageFont.load_default()

        cover = Image.new("RGB", (1600, 2400), "white")
        draw = ImageDraw.Draw(cover)
        draw.text((800, 900), "FreeCAD", font=load_font(190), fill="black", anchor="mm")
        draw.text((800, 1150), "User Manual", font=load_font(130), fill="black", anchor="mm")
        draw.text((800, 1450), datetime.now().strftime("%Y-%m-%d"),
                  font=load_font(70), fill="gray", anchor="mm")
        buf = BytesIO()
        cover.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def create_epub(self, output_file):
        print(f"Building EPUB {output_file}...")
        book = epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title("FreeCAD User Manual")
        book.set_language("en")
        book.add_author("FreeCAD Community")
        book.add_metadata("DC", "source", BASE)
        book.add_metadata("DC", "rights", ATTRIBUTION)
        book.set_cover("cover.jpg", self.generate_cover())

        css = epub.EpubItem(uid="style_main", file_name="style/main.css",
                            media_type="text/css", content=EPUB_CSS)
        book.add_item(css)

        def epub_href(chapter, fragment):
            return f"chapter_{chapter['number']}.xhtml" + (f"#{fragment}" if fragment else "")

        seen_images = {}
        chapter_items = []
        for c in self.chapters:
            soup = BeautifulSoup(self._localise_links(c["html"], epub_href), "html.parser")
            for img in soup.find_all("img"):
                m = re.match(r"data:(image/(?:png|jpeg));base64,(.*)", img.get("src", ""), re.S)
                if not m:
                    continue
                mime, raw = m.group(1), base64.b64decode(m.group(2))
                digest = hashlib.md5(raw).hexdigest()
                if digest not in seen_images:
                    ext = "png" if mime == "image/png" else "jpg"
                    name = f"images/{digest}.{ext}"
                    seen_images[digest] = name
                    book.add_item(epub.EpubItem(uid=f"img_{digest}", file_name=name,
                                                media_type=mime, content=raw))
                img["src"] = seen_images[digest]

            item = epub.EpubHtml(title=c["title"], file_name=f"chapter_{c['number']}.xhtml",
                                 lang="en")
            item.content = str(soup)
            item.add_link(href="style/main.css", rel="stylesheet", type="text/css")
            book.add_item(item)
            chapter_items.append(item)

        book.toc = tuple(chapter_items)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["cover", "nav"] + chapter_items
        epub.write_epub(output_file, book, {})
        print(f"Created {output_file}")


def main():
    ap = argparse.ArgumentParser(description="Convert the FreeCAD wiki manual to PDF/EPUB")
    ap.add_argument("--pdf", default="FreeCAD_User_Manual.pdf")
    ap.add_argument("--epub", default="FreeCAD_User_Manual.epub")
    ap.add_argument("--no-epub", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--max-chapters", type=int, default=None, help="limit pages (for testing)")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between page requests")
    ap.add_argument("--contact", default=None,
                    help="your email, added to the User-Agent so wiki admins can reach you")
    args = ap.parse_args()

    conv = FreeCADManualConverter(delay=args.delay, max_chapters=args.max_chapters,
                                  contact=args.contact)
    conv.crawl()
    if not conv.chapters:
        sys.exit("No chapters were downloaded - check your internet connection.")
    if not args.no_pdf:
        conv.build_pdf(args.pdf)
    if not args.no_epub:
        conv.create_epub(args.epub)


if __name__ == "__main__":
    main()
