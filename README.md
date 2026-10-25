# ShopifyCsvFix — Product CSV Pre-Import Audit, Fix & Re-Check

Shopify's importer silently ignores misspelled columns and rejects files
for bad values — usually discovered one failed import at a time.
ShopifyCsvFix audits your product CSV the way the importer sees it, repairs
the mechanical errors, then **re-audits the repaired file**. 100% local.

## What it fixes on its own
- Column aliases renamed to the exact headers Shopify expects
  (`SKU` → `Variant SKU`, `Qty` → `Variant Inventory Qty`, `Image URL` → `Image Src`, …)
- Prices cleaned to plain numbers (`$1,299.00` → `1299.00`)
- Float quantities made integers (`10.0` → `10`)
- Boolean spellings normalized (`yes`/`TRUE`/`no` → `true`/`false`)
- Tag spacing normalized; relative image URLs made absolute when the file's
  own rows establish a single image domain

## What it reports, but never silently changes
- Duplicate variants (same handle + option values) — merging them is your call
- Variant rows missing a value for a named option
- Prices that aren't numbers at all; missing titles on a handle's first row

## Verified behaviour
On a seeded 5-row import file with 14 planted problems, ShopifyCsvFix
repaired 11 (including 4 header renames) and the re-check confirmed the
remaining 3 blocking errors with 0 new issues introduced.

## Run from source
```
python shopify_fix.py products_export.csv output_folder
```
Writes `<name>_fixed.csv` and `fix_report.md`. Standard library only.
The Windows app wraps the same engine.

## Scope
The CSV file itself (columns, formats, variant structure). Your store's
existing products, locations and inventory settings are not visible from
the file and are out of scope.
