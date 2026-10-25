#!/usr/bin/env python3
"""
ShopifyCsvFix — Shopify product CSV pre-import audit, repair & re-check.

Shopify's importer silently ignores misspelled columns and rejects files
for bad values. This engine:
  1. Audits the CSV against the importer's deterministic rules (required
     columns, per-handle title rule, variant uniqueness, value formats).
  2. Repairs the mechanical problems: known header aliases, currency
     symbols in prices, float quantities, boolean spellings, padded tags,
     relative image URLs when the file's own rows establish one domain.
  3. Re-audits the repaired file and reports what remains — duplicate
     variants and missing option values need the seller's decision and
     are never silently merged or invented.

Local only. Standard library only.
"""
import copy
import csv
import io
import os
import re
import sys
from urllib.parse import urlparse

ALIASES = {
    "sku": "Variant SKU", "product sku": "Variant SKU",
    "qty": "Variant Inventory Qty", "quantity": "Variant Inventory Qty",
    "inventory quantity": "Variant Inventory Qty", "stock": "Variant Inventory Qty",
    "price": "Variant Price",
    "compare at price": "Variant Compare At Price", "compare-at-price": "Variant Compare At Price",
    "image": "Image Src", "image url": "Image Src", "image link": "Image Src",
    "product title": "Title", "name": "Title",
    "barcode": "Variant Barcode", "weight": "Variant Weight",
    "vendor name": "Vendor",
}
BOOL_COLS = ["Published", "Variant Requires Shipping", "Variant Taxable",
             "Variant Inventory Policy", "Gift Card"]
BOOL_MAP = {"yes": "true", "y": "true", "1": "true", "no": "false", "n": "false", "0": "false",
            "TRUE": "true", "FALSE": "false", "True": "true", "False": "false"}


def check_and_fix(rows, fields):
    issues, fixes = [], []

    def issue(sev, row, field, msg):
        issues.append({"sev": sev, "handle": row.get("Handle", "?"), "field": field, "msg": msg})

    def fix(row, field, new, note):
        old = row.get(field, "")
        if old != new:
            row[field] = new
            fixes.append({"handle": row.get("Handle", "?"), "field": field,
                          "old": old, "new": new, "note": note})

    rename = {}
    for f in fields:
        target = ALIASES.get(f.strip().lower())
        if target and target not in fields and f != target:
            rename[f] = target
    if rename:
        for r in rows:
            for old, new in rename.items():
                r[new] = r.pop(old, "")
        fields = [rename.get(f, f) for f in fields]
        for old, new in rename.items():
            fixes.append({"handle": "(header)", "field": old, "old": old, "new": new,
                          "note": f"column renamed to the name Shopify's importer expects ('{new}')"})

    if "Handle" not in fields:
        issue("ERROR", {}, "Handle", "no 'Handle' column — Shopify cannot import the file at all")
        return issues, fixes, fields
    if "Title" not in fields:
        issue("ERROR", {}, "Title", "no 'Title' column — new products cannot be created without it")

    domains = {}
    for r in rows:
        v = (r.get("Image Src") or "").strip()
        if v.startswith("http"):
            d = urlparse(v)
            if d.netloc:
                domains[d.netloc] = domains.get(d.netloc, 0) + 1
    main_domain = max(domains, key=domains.get) if domains else None

    seen_handles = set()
    seen_variants = {}
    for idx, r in enumerate(rows):
        h = (r.get("Handle") or "").strip()
        if not h:
            issue("ERROR", r, "Handle", f"row {idx + 2} has an empty Handle — the row will be skipped/rejected")
            continue
        first_of_handle = h not in seen_handles
        seen_handles.add(h)
        if first_of_handle and "Title" in fields and not (r.get("Title") or "").strip():
            issue("ERROR", r, "Title", "first row for this handle has no Title — Shopify needs a title to create the product")

        key = (h, (r.get("Option1 Value") or "").strip(), (r.get("Option2 Value") or "").strip(),
               (r.get("Option3 Value") or "").strip())
        has_options = any((r.get(f"Option{i} Name") or "").strip() for i in (1, 2, 3)) or \
                      any(key[i] for i in (1, 2, 3))
        if has_options:
            if key in seen_variants:
                issue("ERROR", r, "Option1 Value", "duplicate variant: same handle and option values as an earlier row — Shopify will reject or overwrite it; merge or differentiate the rows")
            seen_variants[key] = True
        for i in (1, 2, 3):
            if (r.get(f"Option{i} Name") or "").strip() and not (r.get(f"Option{i} Value") or "").strip():
                if first_of_handle or (r.get(f"Option{i} Value") is not None and r.get("Variant SKU")):
                    issue("ERROR", r, f"Option{i} Value", f"Option{i} Name is set but a variant row has no Option{i} Value — every variant needs a value for each named option")

        p = (r.get("Variant Price") or "").strip()
        if p:
            cleaned = p.replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
            if re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
                if cleaned != p:
                    fix(r, "Variant Price", cleaned, "price cleaned to a plain number (Shopify rejects currency symbols/thousands separators)")
            else:
                issue("ERROR", r, "Variant Price", f"price '{p}' is not a number — the import will fail for this row")
        cp = (r.get("Variant Compare At Price") or "").strip()
        if cp:
            cleaned = cp.replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
            if re.fullmatch(r"\d+(\.\d{1,2})?", cleaned) and cleaned != cp:
                fix(r, "Variant Compare At Price", cleaned, "compare-at price cleaned to a plain number")

        q = (r.get("Variant Inventory Qty") or "").strip()
        if q:
            if re.fullmatch(r"\d+\.0", q):
                fix(r, "Variant Inventory Qty", q[:-2], "quantity was a float ('10.0') — Shopify expects an integer")
            elif not re.fullmatch(r"-?\d+", q):
                issue("ERROR", r, "Variant Inventory Qty", f"quantity '{q}' is not an integer")

        for b in BOOL_COLS:
            v = (r.get(b) or "").strip()
            if v and v not in ("true", "false") and b != "Variant Inventory Policy":
                if v in BOOL_MAP:
                    fix(r, b, BOOL_MAP[v], f"boolean value normalized to '{BOOL_MAP[v]}' (Shopify accepts only true/false)")
                elif b in ("Published",):
                    issue("WARN", r, b, f"'{b}' value '{v}' is not true/false — the importer may treat the product as unpublished")

        img = (r.get("Image Src") or "").strip()
        if img and not img.startswith("http"):
            if img.startswith("/") and main_domain:
                fix(r, "Image Src", f"https://{main_domain}{img}", "relative image URL made absolute using the domain used by this file's other images")
            else:
                issue("ERROR", r, "Image Src", f"image '{img}' is not a full public URL — Shopify downloads images at import, so the URL must be reachable online")

        tags = r.get("Tags")
        if tags and tags != ", ".join(t.strip() for t in tags.split(",")):
            fix(r, "Tags", ", ".join(t.strip() for t in tags.split(",") if t.strip()),
                "tag spacing normalized (leading/trailing spaces create junk tags)")
    return issues, fixes, fields


def read_csv(path):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader], reader.fieldnames or []


def run_shopifyfix(src_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    rows, fields = read_csv(src_path)
    base = os.path.splitext(os.path.basename(src_path))[0]
    before, fixes, fields = check_and_fix(rows, fields)
    remaining, _, _ = check_and_fix(copy.deepcopy(rows), list(fields))
    fixed_path = os.path.join(outdir, base + "_fixed.csv")
    with open(fixed_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    def cnt(lst, sev):
        return sum(1 for i in lst if i["sev"] == sev)

    errs = cnt(remaining, "ERROR")
    lines = ["# ShopifyCsvFix — pre-import repair & re-check report", "",
             f"Source file: {os.path.basename(src_path)}  ·  Rows: {len(rows)}", "",
             "## Summary",
             f"- Problems found: {len(before) + len(fixes)} in total",
             f"- Auto-fixed: {len(fixes)}",
             f"- Needing your input: {len(before)} ({cnt(before,'ERROR')} errors, {cnt(before,'WARN')} warnings)",
             f"- Remaining after re-check: {len(remaining)} ({errs} errors, {cnt(remaining,'WARN')} warnings)", "",
             "## What was fixed automatically"]
    lines += [f"- [{fx['handle']}] {fx['field']}: '{fx['old']}' -> '{fx['new']}' ({fx['note']})" for fx in fixes] or ["- nothing"]
    lines += ["", "## What still needs your input (cannot be auto-fixed)"]
    lines += [f"- [{i['sev']}] [{i['handle']}] {i['field']}: {i['msg']}" for i in remaining] or \
             ["- nothing — the repaired file passes every check in this audit set"]
    lines += ["", "## Re-check verdict",
              f"- {'PASS with warnings' if errs == 0 else 'NOT READY'}: {errs} blocking errors remain. "
              "Scope note: this audit covers the CSV file itself (columns, formats, variant structure). "
              "It cannot see your store's existing products, locations or inventory settings."]
    report_path = os.path.join(outdir, "fix_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"rows": len(rows), "found": len(before), "fixed": len(fixes),
            "remaining": len(remaining), "errors_remaining": errs,
            "fixed_path": fixed_path, "report_path": report_path}


def main(argv):
    if len(argv) != 3:
        print("usage: shopify_fix.py <products.csv> <outdir>")
        return 2
    s = run_shopifyfix(argv[1], argv[2])
    print(f"rows={s['rows']} found={s['found']} fixed={s['fixed']} remaining={s['remaining']} errors_remaining={s['errors_remaining']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
