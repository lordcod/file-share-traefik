"""Build the public SwimTab catalog from complete SPLASH HTML publications."""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote


ROOT = Path(os.getenv("CATALOG_ROOT", "/srv/ftp"))
OUTPUT = Path(os.getenv("CATALOG_OUTPUT", "/srv/catalog/catalog.json"))
INTERVAL = max(5, int(os.getenv("CATALOG_INTERVAL_SECONDS", "60")))
SETTLE_SECONDS = 5
MAX_HTML_BYTES = 16 * 1024 * 1024
DATE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
UPDATED = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})(?::(\d{2}))?\b")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class SplashHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = {"title": [], "updated": [], "session": []}
        self.sessions = []
        self.splash = False
        self.closed_html = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").lower() == "generator":
            self.splash = "splash meet manager" in attrs.get("content", "").lower()
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        markers = set()
        if tag == "title":
            markers.add("title")
        if attrs.get("id") == "lastupdate":
            markers.add("updated")
        if tag == "td" and "title1" in attrs.get("class", "").split():
            markers.add("session")
            self.parts["session"] = []
        self.stack.append((tag, markers))

    def handle_endtag(self, tag):
        if tag == "html":
            self.closed_html = True
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if any("session" in markers for _, markers in self.stack[i:]):
                    self.sessions.append(" ".join(self.parts["session"]))
                del self.stack[i:]
                break

    def handle_data(self, data):
        markers = set().union(*(markers for _, markers in self.stack))
        for marker in markers:
            self.parts[marker].append(data)


def read_entry(path, entry_id):
    before = path.stat()
    if before.st_size > MAX_HTML_BYTES:
        raise ValueError("HTML exceeds size limit")
    if time.time() - before.st_mtime < SETTLE_SECONDS:
        raise ValueError("upload has not settled yet")
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("HTML changed while reading")
    # SPLASH exports can use UTF-8 or explicitly declared Windows-1251.
    charset = re.search(rb'charset\s*=\s*["\x27]?\s*([\w-]+)', raw[:8192], re.I)
    encoding = charset.group(1).decode("ascii").lower() if charset else "utf-8-sig"
    if encoding not in {"utf-8", "utf-8-sig", "windows-1251", "cp1251"}:
        raise ValueError("unsupported HTML encoding")
    parser = SplashHTML()
    parser.feed(raw.decode(encoding))
    parser.close()
    title = " ".join("".join(parser.parts["title"]).split())
    title = re.sub(r"\s*-\s*SPLASH Meet Manager\b.*$", "", title, flags=re.I).strip()
    if not parser.splash or not parser.closed_html or not title:
        raise ValueError("not a complete SPLASH publication with a title")
    dates = set()
    for heading in parser.sessions:
        for value in DATE.findall(heading):
            try:
                dates.add(datetime.strptime(value, "%d.%m.%Y").date().isoformat())
            except ValueError:
                pass
    updated = None
    match = UPDATED.search(" ".join(parser.parts["updated"]))
    if match:
        try:
            updated = datetime.strptime(
                f"{match[1]} {match[2]}:{match[3] or '00'}", "%d.%m.%Y %H:%M:%S"
            ).isoformat()
        except ValueError:
            pass
    year, series, code = entry_id.split("/")
    return {
        "id": entry_id,
        "year": int(year),
        "series": series,
        "code": code,
        "title": title,
        "url": "/" + quote(entry_id, safe="/") + "/index.html",
        "sessionDates": sorted(dates),
        "sourceUpdatedAtLocal": updated,
    }


def candidates():
    """Only year/series/code; a directory alone is not a publication."""
    found = {}
    for year in ROOT.iterdir():
        if year.is_symlink() or not re.fullmatch(r"[0-9]{4}", year.name) or not year.is_dir():
            continue
        for series in year.iterdir():
            if series.is_symlink() or series.name.startswith((".", "_")) or not series.is_dir():
                continue
            for competition in series.iterdir():
                if competition.is_symlink() or competition.name.startswith((".", "_")) or not competition.is_dir():
                    continue
                path = competition / "index.html"
                if not path.is_symlink() and path.is_file():
                    found[path.relative_to(ROOT).parent.as_posix()] = path
    return found


def load_previous():
    try:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != 1:
            raise ValueError("unsupported saved schema")
        return {entry["id"]: entry for entry in payload["competitions"]}
    except FileNotFoundError:
        return {}
    except (ValueError, KeyError, TypeError):
        logging.warning("Saved catalog is invalid; rebuilding from publications")
        return {}


def publish(entries):
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "competitions": sorted(entries.values(), key=lambda item: (-item["year"], item["series"], item["code"])),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, OUTPUT)


def main():
    entries = load_previous()
    while True:
        try:
            found = candidates()
            # Retain last valid data during replacement/removal of index.html.
            # Only removal of the entire competition directory removes its entry.
            current = {}
            for entry_id, entry in entries.items():
                directory = ROOT / entry_id
                if directory.is_dir() and not directory.is_symlink():
                    current[entry_id] = entry
            for entry_id, path in found.items():
                try:
                    current[entry_id] = read_entry(path, entry_id)
                except (OSError, ValueError) as error:
                    logging.warning("Keeping previous entry for %s: %s", entry_id, error)
            if current != entries or not OUTPUT.exists():
                publish(current)
                logging.info("Published catalog with %d competitions", len(current))
            entries = current
        except (OSError, ValueError) as error:
            logging.error("Catalog scan failed; keeping previous catalog: %s", error)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
