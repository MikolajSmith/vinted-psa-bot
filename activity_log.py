import csv
from pathlib import Path

FIELDS = [
    "checked_at",
    "listing_id",
    "title",
    "url",
    "listing_price",
    "listing_currency",
    "grade",
    "reference_price_usd",
    "sample_count",
    "discount_percent",
    "match_score",
    "decision",
]


def log_row(activity_log_file: Path, row: dict):
    is_new = not activity_log_file.exists()
    with activity_log_file.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FIELDS})
