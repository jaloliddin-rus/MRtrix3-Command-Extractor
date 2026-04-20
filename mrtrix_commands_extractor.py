import hashlib
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE = "https://mrtrix.readthedocs.io/en/latest/"
COMMANDS_LIST_RST = urljoin(BASE, "_sources/reference/commands_list.rst.txt")

_session = requests.Session()


def _cache_dir():
    return Path(os.environ.get("MRTRIX_EXTRACTOR_CACHE_DIR", ".mrtrix_cache"))


def fetch(url):
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = cache / key
    if path.exists():
        return path.read_text(encoding="utf-8")
    resp = _session.get(url, timeout=15)
    resp.raise_for_status()
    text = resp.text
    path.write_text(text, encoding="utf-8")
    return text


def _normalize_synopsis(text):
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.split())


def extract_commands_and_synopsis():
    text = fetch(COMMANDS_LIST_RST)
    pattern = r":ref:`([^`]+)`,\s*\"([^\"]+)\""
    matches = re.findall(pattern, text)
    commands = []
    for name, synopsis in matches:
        name = " ".join(name.split())
        synopsis = " ".join(synopsis.split())
        commands.append({"name": name, "synopsis": synopsis})
    return commands


def get_section_div(soup, h2_text):
    header = soup.find(
        lambda tag: tag.name == "h2"
        and h2_text.lower() in tag.get_text(strip=True).lower()
    )
    return header.parent if header else None


def get_all_section_divs(soup, h2_text):
    headers = soup.find_all(
        lambda tag: tag.name == "h2"
        and h2_text.lower() in tag.get_text(strip=True).lower()
    )
    return [h.parent for h in headers]


def parse_usage_from_section(section):
    usage_cmdline = None
    positional_args = []
    if section is None:
        return usage_cmdline, positional_args
    for anchor in section.find_all("a", class_="headerlink"):
        anchor.decompose()
    pre = section.find("pre")
    if pre:
        usage_cmdline = " ".join(pre.get_text().split())
    for li in section.find_all("li"):
        t = " ".join(li.get_text().split())
        if ":" in t:
            name, desc = t.split(":", 1)
            positional_args.append(
                {"name": name.strip().strip("*"), "description": desc.strip()}
            )
    return usage_cmdline, positional_args


def parse_usage_section(soup):
    return parse_usage_from_section(get_section_div(soup, "Usage"))


def parse_options_from_section(options_section):
    options = []
    if options_section is None:
        return options

    for anchor in options_section.find_all("a", class_="headerlink"):
        anchor.decompose()

    standard_headers = options_section.find_all(
        lambda tag: tag.name in ("h3", "h4")
        and "standard options" in tag.get_text(strip=True).lower()
    )
    standard_lis = set()
    for header in standard_headers:
        current = header
        while True:
            current = current.find_next_sibling()
            if current is None or current.name in ("h2", "h3", "h4"):
                break
            if current.name == "ul":
                for li in current.find_all("li", recursive=False):
                    standard_lis.add(li)

    li_to_subsection = {}
    for header in options_section.find_all(lambda tag: tag.name in ("h3", "h4")):
        heading_text = " ".join(header.get_text().split())
        current = header
        while True:
            current = current.find_next_sibling()
            if current is None or current.name in ("h2", "h3", "h4"):
                break
            if current.name == "ul":
                for li in current.find_all("li", recursive=False):
                    li_to_subsection[li] = heading_text

    for li in options_section.find_all("li"):
        text = " ".join(li.get_text().split())
        if not text:
            continue

        strong = li.find("strong")
        if strong:
            flag_part = " ".join(strong.get_text().split())
            if not flag_part.startswith("-"):
                continue
            desc = text.replace(flag_part, "", 1).lstrip()
            if desc and desc[0] in ":-\u2013\u2014":
                desc = desc[1:].lstrip()
            desc = desc.rstrip()
        else:
            parts = text.split(None, 2)
            if len(parts) >= 2 and parts[0].startswith("-"):
                flag_part = " ".join(parts[:2])
                desc = parts[2] if len(parts) == 3 else ""
            else:
                continue

        options.append(
            {
                "flag": flag_part,
                "description": desc,
                "category": "standard" if li in standard_lis else "options",
                "subsection": li_to_subsection.get(li),
            }
        )

    return options


def parse_options_section(soup):
    return parse_options_from_section(get_section_div(soup, "Options"))


def _algorithm_name_from_usage(usage_line, command_name):
    if not usage_line:
        return None
    tokens = usage_line.split()
    if len(tokens) >= 2 and tokens[0] == command_name:
        candidate = tokens[1]
        if candidate.startswith("["):
            return None
        return candidate
    return None


def parse_algorithms(soup, command_name):
    usage_sections = get_all_section_divs(soup, "Usage")
    options_sections = get_all_section_divs(soup, "Options")
    algorithms = {}
    # First Usage/Options block is the dispatcher (handled by parse_command_page).
    # Pair remaining Usage blocks with the Options block that follows each in doc order.
    for usage_div in usage_sections[1:]:
        usage, positional = parse_usage_from_section(usage_div)
        alg_name = _algorithm_name_from_usage(usage, command_name)
        if not alg_name:
            continue
        # Find the first Options div that appears after this Usage div in the document.
        options_div = None
        for od in options_sections:
            if _follows(od, usage_div):
                options_div = od
                break
        options = parse_options_from_section(options_div)
        algorithms[alg_name] = {
            "usage": usage,
            "positional_args": positional,
            "options": options,
        }
    return algorithms


def _follows(a, b):
    # True if element a appears after element b in document order.
    for elem in b.find_all_next():
        if elem is a:
            return True
    return False


def parse_examples_section(soup):
    examples = []
    header = soup.find(
        lambda tag: tag.name in ("h2", "h3")
        and tag.get_text(strip=True).lower().startswith(("example usages", "example usage", "examples"))
    )
    if not header:
        return examples
    section = header.parent
    for anchor in section.find_all("a", class_="headerlink"):
        anchor.decompose()
    pres = section.find_all("pre")
    for pre in pres:
        text = pre.get_text()
        cmd = " ".join(text.split())
        if cmd.startswith("$ "):
            cmd = cmd[2:].lstrip()
        description = ""
        prev = pre.find_previous_sibling()
        while prev is not None and prev.name not in ("p",):
            prev = prev.find_previous_sibling()
        if prev is not None and prev.name == "p":
            description = " ".join(prev.get_text().split())
        examples.append({"command": cmd, "description": description})
    return examples


def parse_command_page(name):
    url = urljoin(BASE, f"reference/commands/{name}.html")
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1:
        for anchor in h1.find_all("a", class_="headerlink"):
            anchor.decompose()
        title = " ".join(h1.get_text().split())
    else:
        title = name

    synopsis_section = get_section_div(soup, "Synopsis")
    synopsis_text = None
    if synopsis_section:
        for anchor in synopsis_section.find_all("a", class_="headerlink"):
            anchor.decompose()
        p = synopsis_section.find("p")
        if p:
            synopsis_text = " ".join(p.get_text().split())
        else:
            synopsis_text = " ".join(synopsis_section.get_text().split())

    usage_cmdline, positional_args = parse_usage_section(soup)
    options = parse_options_section(soup)
    algorithms = parse_algorithms(soup, name)
    examples = parse_examples_section(soup)

    return {
        "title": title,
        "synopsis": synopsis_text,
        "usage": usage_cmdline,
        "positional_args": positional_args,
        "options": options,
        "algorithms": algorithms,
        "examples": examples,
        "url": url,
    }


def _parse_one(cmd):
    name = cmd["name"]
    try:
        return name, parse_command_page(name)
    except Exception as e:
        return name, e


def main(output_path="./mrtrix_commands.json"):
    commands = extract_commands_and_synopsis()
    workers = int(os.environ.get("MRTRIX_EXTRACTOR_WORKERS", "8"))

    parsed = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (name, result) in enumerate(pool.map(_parse_one, commands), start=1):
            print(f"[{i}/{len(commands)}] Parsed {name}")
            if isinstance(result, Exception):
                print(f"  !! Failed to parse {name}: {result}")
                continue
            parsed[name] = result

    results = {}
    for cmd in commands:
        name = cmd["name"]
        page_info = parsed.get(name)
        if page_info is None:
            continue

        list_syn = _normalize_synopsis(cmd["synopsis"])
        page_syn = _normalize_synopsis(page_info.get("synopsis"))
        synopsis = list_syn or page_syn

        results[name] = {
            "title": page_info["title"],
            "synopsis": synopsis,
            "usage": page_info["usage"],
            "positional_args": page_info["positional_args"],
            "options": page_info["options"],
            "algorithms": page_info.get("algorithms", {}),
            "examples": page_info.get("examples", []),
            "url": page_info["url"],
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(results)} commands to {output_path}")


if __name__ == "__main__":
    main()
