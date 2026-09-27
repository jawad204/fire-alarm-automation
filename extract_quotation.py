"""
Step 1 of 2 - read a fire alarm quotation PDF and SAVE the result as JSON.

    python extract_quotation.py 1942.pdf

Sends every page of the PDF - no one has to know or pass which page holds
the BOQ, since that differs between quotations. Writes 1942.json next to
the PDF. Refuses anything over MAX_PAGES, on the assumption that a very
long file is a whole job bundle rather than a single quotation.

If you run it with no arguments it falls back to DEFAULT_PDF, so the VS
Code play button also works.

This script knows nothing about Excel. It reads a page and writes a file.

Setup:
    pip install anthropic pymupdf python-dotenv

.env next to this script:
    ANTHROPIC_API_KEY=sk-ant-your-key-here

.gitignore next to this script:
    .env
"""

import base64
import json
import os
import pathlib
import re
import sys

import fitz
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Baked in so the built .exe works with no setup on the machine it runs on.
# Anyone who unpacks the .exe could in principle recover this string - that
# trade-off is fine for a program handed to one person you trust, not for
# wide distribution. An ANTHROPIC_API_KEY set in the environment always
# wins over this, so your own dev machine keeps using its own key.
BAKED_API_KEY = "REDACTED"


MODEL = "claude-sonnet-5"

DEFAULT_PDF = "1942.pdf"

MAX_PAGES = 12   # a normal quotation is 2-6 pages; more than this is
                 # probably a whole job bundle, not a quotation - refuse
                 # rather than pay to read 11 irrelevant pages.

PROMPT = """These pages are a fire alarm quotation. Extract the following.

customer_name   - the company the quotation is addressed to.
                  Remove any "M/s" prefix.
project_name    - the "Project" field
quotation_ref   - the numeric part only. From "AIC/239581/MS/26" return 239581
value           - the final total INCLUDING VAT, as a plain number, no commas
payment_term    - ONE WORD only: "advance", "LPO", or "credit".
                  Choose whichever best matches the payment terms section.
line_items      - EVERY row of the Bill of Quantities table, in order.
                  Each row is an object with:
                    sl          - the Sl. number as written
                    description - the description text exactly as printed
                    qty         - the quantity. Use the string "Lot" if it says Lot
                    unit_price  - number, or null if blank
                    total_price - number

Include every row, including relocation, installation and testing lines.
Do not filter or interpret them.

Return ONLY a JSON object. No explanation, no markdown.
If a field is not present, use null. Never guess a value."""


def all_pages(path, limit=MAX_PAGES):
    """Every page of the PDF, 0-based. No one has to know or supply which
    page holds the BOQ - the model looks at all of them and works it out.

    Refuses anything unusually long: that is more likely a whole job bundle
    (requisition, invoice, bank slip, quotation...) than a single quotation,
    and reading it in full would be five times the cost for no benefit -
    worse, it raises the odds of pulling a number off the wrong document.
    """
    doc = fitz.open(path)
    count = len(doc)
    doc.close()
    if count > limit:
        raise SystemExit(
            f"{path} has {count} pages - that looks like a job bundle, "
            f"not a single quotation. Split out just the quotation and retry."
        )
    return list(range(count))


def page_images(path, pages, dpi=150):
    """Render the chosen PDF pages to base64 PNGs the API can read.

    150 dpi is enough for printed text. Higher dpi multiplies the token
    cost for no gain.
    """
    doc = fitz.open(path)
    blocks = []
    for i in pages:
        pix = doc[i].get_pixmap(dpi=dpi)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(pix.tobytes("png")).decode(),
                },
            }
        )
    doc.close()
    return blocks


def strip_fences(text):
    """The model sometimes wraps JSON in ```json fences despite being asked
    not to. Handle it here rather than arguing with the prompt."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract(path, pages):
    """Send the pages to the model. Returns (data, usage)."""
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or BAKED_API_KEY)

    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,           # thinking tokens count against this too
        messages=[
            {
                "role": "user",
                "content": page_images(path, pages) + [{"type": "text", "text": PROMPT}],
            }
        ],
    )

    # resp.content is a LIST of blocks - thinking, text, later tool_use.
    # Never assume content[0] is the text you want.
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()

    if resp.stop_reason == "max_tokens":
        raise SystemExit("Reply was cut off by max_tokens. Raise the limit and retry.")

    return json.loads(strip_fences(raw)), resp.usage


def save_json(pdf_path, data):
    """Write 1942.json next to 1942.pdf and return the absolute path."""
    out = pathlib.Path(pdf_path).with_suffix(".json")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out.resolve()


if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("No API key found. Check your .env file.")

    if len(sys.argv) >= 2:
        pdf = sys.argv[1]
    else:
        pdf = DEFAULT_PDF
        print(f"(no argument given - using {pdf})")

    if not pathlib.Path(pdf).exists():
        raise SystemExit(f"{pdf} not found in {pathlib.Path.cwd()}")

    pages = all_pages(pdf)
    print(f"(reading all {len(pages)} pages of {pdf})")

    data, usage = extract(pdf, pages)

    saved = save_json(pdf, data)

    print("=== extracted ===")
    for key in ("customer_name", "project_name", "quotation_ref", "value", "payment_term"):
        print(f"{key:15} = {data.get(key)!r}")

    items = data.get("line_items") or []
    print(f"\n=== bill of quantities ({len(items)} rows) ===")
    for item in items:
        print(f"  {str(item.get('sl')):>3}  {str(item.get('description'))[:48]:48}  qty {item.get('qty')}")

    cost = usage.input_tokens / 1e6 * 2 + usage.output_tokens / 1e6 * 10
    print(f"\nSAVED -> {saved}")
    print(f"tokens: {usage.input_tokens} in / {usage.output_tokens} out   cost ${cost:.4f}")
