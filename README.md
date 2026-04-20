# MRtrix3 Command Extractor

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A small scraper that turns the [MRtrix3](https://www.mrtrix.org/) command documentation into one structured JSON index of every command: its usage, options, algorithms, and examples.

## Why

MRtrix3 ships **125 command-line tools**. Their canonical documentation is a set of HTML pages on readthedocs. If you want to do anything programmatic with those commands — build autocompletion, generate tool wrappers, feed an LLM agent, check option validity — you need a structured reference. This project produces one.

The included `mrtrix_commands.json` is the output as of the latest scrape; re-run the script any time the upstream docs change.

## What it captures

For each command:

- **Title and synopsis** — the one-line description.
- **Dispatcher-level usage, positional args, options** — what you get from the command's main help page.
- **Per-algorithm sub-commands** — commands like `5ttgen`, `dwi2response`, `dwibiascorrect`, and `dwinormalise` dispatch into algorithm-specific variants (`5ttgen fsl`, `dwi2response msmt_5tt`, …). Each variant's own usage, positional arguments, and options are captured separately.
- **Subsection-tagged options** — each option carries its `<h3>` heading from the docs (e.g. *"DW gradient table import options"*, *"Standard options"*), so duplicated flag names that depend on algorithm or filter mode stay disambiguated.
- **Example usages** — verbatim from the docs' *Example usages* section, including the tricky cases (e.g. `transformconvert` whose real arity is only visible in examples).

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.8+.

## Usage

```bash
python3 mrtrix_commands_extractor.py
```

Writes `mrtrix_commands.json` in the current directory.

The first run fetches ~126 pages from readthedocs (a few seconds with the default 8 concurrent workers). Subsequent runs are effectively instant — all pages are cached on disk under `.mrtrix_cache/`.

To refresh after an upstream docs update:

```bash
rm -rf .mrtrix_cache && python3 mrtrix_commands_extractor.py
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MRTRIX_EXTRACTOR_CACHE_DIR` | `.mrtrix_cache` | Location of the page cache |
| `MRTRIX_EXTRACTOR_WORKERS` | `8` | HTTP worker count |

## Output schema

```jsonc
{
  "<command_name>": {
    "title": "...",
    "synopsis": "...",
    "usage": "command [ options ] input output",
    "positional_args": [
      { "name": "input", "description": "..." }
    ],
    "options": [
      {
        "flag": "-foo value",
        "description": "...",
        "category": "options",          // "options" or "standard"
        "subsection": "..."              // e.g. "DW shell selection options", null if none
      }
    ],
    "algorithms": {                      // empty {} for commands with no algorithm dispatch
      "<algorithm_name>": {
        "usage": "command algorithm input output [ options ]",
        "positional_args": [ ... ],
        "options": [ ... ]
      }
    },
    "examples": [
      { "command": "...", "description": "..." }
    ],
    "url": "https://mrtrix.readthedocs.io/..."
  }
}
```

## Example: `5ttgen`

The dispatcher page gives only the top-level `algorithm [ options ] ...` shell; the real arity lives on per-algorithm sub-pages. The extractor captures both:

```jsonc
{
  "5ttgen": {
    "usage": "5ttgen algorithm [ options ] ...",
    "positional_args": [
      { "name": "algorithm", "description": "Select the algorithm ... Options are: freesurfer, fsl, gif, hsvs" }
    ],
    "algorithms": {
      "fsl": {
        "usage": "5ttgen fsl input output [ options ]",
        "positional_args": [
          { "name": "input",  "description": "..." },
          { "name": "output", "description": "..." }
        ],
        "options": [
          { "flag": "-t2 image",   "description": "provide a T2-weighted image ..." },
          { "flag": "-mask image", "description": "manually provide a brain mask ..." },
          { "flag": "-premasked",  "description": "indicate that brain masking has already been applied ..." }
        ]
      },
      "freesurfer": { /* ... -lut etc. ... */ },
      "gif":        { /* ... */ },
      "hsvs":       { /* ... */ }
    }
  }
}
```

## License

[MIT](LICENSE).
