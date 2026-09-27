"""
The one script your brother runs.

    python run.py 1855.pdf

Does the whole job: reads the quotation, shows what it found, waits for
you to confirm it against the paper, then writes the sheet row and the
material requisition. Nothing is written until you type y.

If run with no argument, it asks for a file - so double-clicking a
DRAG-AND-DROP shortcut, or dragging a PDF onto this script in Explorer,
also works.

The Excel sheet path is NOT in this file - it lives in config.txt next to
the exe (or next to this script, when run as python run.py). That way the
path can differ on every machine this runs on without editing any code.
"""

import datetime
import pathlib
import sys

from extract_quotation import all_pages, extract, save_json
from quotation_to_sheet import TAB, check, supply_lines, clean_qty, write_row
from make_requisition import build


CONFIG_TEMPLATE = """# Path to the fire alarm job sheet (.xlsx).
# Edit the line below to point at your own copy, then save this file.
sheet_path = PASTE THE FULL PATH TO YOUR EXCEL SHEET HERE
"""


def base_dir():
    """The folder this program lives in - the exe's own folder when frozen
    by PyInstaller, or this script's folder otherwise. NOT the current
    working directory, which can be anywhere depending on how it was
    launched (this is exactly what broke the sheet path earlier)."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def load_sheet_path():
    """Read the sheet path from config.txt. If the file doesn't exist yet,
    create a blank template and stop - there's nothing sensible to do
    without a real path, and guessing one would be worse than asking."""
    config_path = base_dir() / "config.txt"

    if not config_path.exists():
        config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        print(f"No config.txt found - created one at:\n  {config_path}")
        print("Open it, paste the full path to your Excel sheet, save, and run this again.")
        input("\nPress Enter to close.")
        raise SystemExit(0)

    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("sheet_path"):
            _, _, value = line.partition("=")
            path = value.strip().strip('"')
            if path and "PASTE THE FULL PATH" not in path:
                return path

    print(f"config.txt exists but has no sheet_path set:\n  {config_path}")
    print("Open it and paste the full path to your Excel sheet.")
    input("\nPress Enter to close.")
    raise SystemExit(0)


def get_pdf_path():
    if len(sys.argv) >= 2:
        return sys.argv[1]
    typed = input("Drag the quotation PDF here and press Enter: ").strip().strip('"')
    return typed


def show_summary(data):
    print("\n  Customer      ", data.get("customer_name"))
    print("  Project       ", data.get("project_name"))
    print("  Quotation     ", data.get("quotation_ref"))
    print("  Value         ", data.get("value"))
    print("  Payment       ", data.get("payment_term"))

    items = supply_lines(data.get("line_items"))
    print("\n  Material requisition")
    for n, item in enumerate(items, start=1):
        desc = str(item.get("description"))[:44]
        print(f"    {n}.  {desc:44} qty {clean_qty(item.get('qty'))}")
    return items


def main():
    sheet_path = load_sheet_path()
    if not pathlib.Path(sheet_path).exists():
        print(f"config.txt points at a sheet that doesn't exist:\n  {sheet_path}")
        print("Check the path in config.txt and try again.")
        input("Press Enter to close.")
        return

    pdf = get_pdf_path()
    if not pdf or not pathlib.Path(pdf).exists():
        print(f"Could not find: {pdf}")
        input("Press Enter to close.")
        return

    print(f"\nReading {pathlib.Path(pdf).name} ...")
    pages = all_pages(pdf)
    data, usage = extract(pdf, pages)
    save_json(pdf, data)

    problems = check(data)
    if problems:
        print("\nThis quotation could not be read reliably:")
        for p in problems:
            print("  -", p)
        print("\nNothing written. Please send this one to Jawad.")
        input("\nPress Enter to close.")
        return

    print(f"\nRead from {pathlib.Path(pdf).name}")
    show_summary(data)

    answer = input("\nDoes this match the quotation? (y/n): ").strip().lower()
    if answer != "y":
        print("\nNothing written. Please send this one to Jawad.")
        input("Press Enter to close.")
        return

    today = datetime.date.today()          # ONE date, used for both the
                                            # sheet row and the requisition,
                                            # so the two can never disagree

    row, job_no = write_row(data, sheet_path, sheet_path, TAB, date=today)

    if row is None:
        print(f"\nThis quotation is already filed as job {job_no}.")
        print("Sheet not touched, but generating the requisition anyway.")
    else:
        print(f"\nWritten to row {row}, job {job_no}.")

    req_path = base_dir() / "requisitions" / f"requisition_{job_no}.pdf"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Saving requisition to: {req_path}")
    try:
        build(data, job_no, req_path, date=today.strftime("%d/%m/%y"))
    except Exception as err:
        print(f"\nCould not save the requisition: {err}")
        print("The job WAS still filed in the sheet above.")
        input("Press Enter to close.")
        return
    print(f"Requisition saved: {req_path.name}")
    input("\nPress Enter to close.")


if __name__ == "__main__":
    main()
