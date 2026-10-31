"""
utils/results_parse.py — Transforms search result sets into various output formats.

Formats supported:
  - Rich terminal table (to_table)
  - HTML report  (export_html)
  - CSV          (export_csv)
  - Excel .xlsx  (export_excel)  — styled: colors, autofit, freeze panes, hyperlinks
  - JSON         (export_json)

Deep searches also pass the values they extracted, and every export then
includes them with the page each one came from.
"""

import json
import os
import csv
import html
import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from rich.table import Table
from cli.ui import THEME, print_success, print_error, make_table
from core.config import DIR_REPORTS


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ScannUs — Search Report</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: #0f1117; color: #e6e6e6; margin: 0; padding: 2rem; }
  header { border-bottom: 1px solid #2a2f3a; padding-bottom: 1rem; margin-bottom: 1.5rem; }
  header h1 { margin: 0 0 .25rem 0; font-size: 1.4rem; color: #00d7ff; letter-spacing: .02em; }
  header .meta { color: #888; font-size: .9rem; }
  .result { background: #161a23; border: 1px solid #232836; border-radius: 8px;
            padding: 1rem 1.25rem; margin-bottom: 1rem; }
  .result .index { color: #ff5fd7; font-size: .75rem; text-transform: uppercase;
                   letter-spacing: .08em; margin-bottom: .25rem; }
  .result h5 { margin: .1rem 0 .5rem 0; font-size: 1rem; color: #ffffff; }
  .result p  { margin: 0 0 .6rem 0; color: #b8b8b8; line-height: 1.45; }
  .result a  { color: #00d7ff; text-decoration: none; word-break: break-all; }
  .result a:hover { text-decoration: underline; }
  .extracted h2 { margin: 2rem 0 .75rem 0; font-size: 1.1rem; color: #00d7ff; }
  .extracted table { width: 100%; border-collapse: collapse; background: #161a23; }
  .extracted th, .extracted td { border: 1px solid #232836; padding: .5rem .75rem;
                                 text-align: left; word-break: break-all; }
  .extracted th { color: #888; }
  .extracted a { color: #00d7ff; text-decoration: none; }
</style>
</head>
<body>
  <header>
    <h1>⬡  ScannUs — Search Report</h1>
    <div class="meta">{{ total }} result(s)</div>
  </header>
  {{ results }}
  {{ extracted }}
</body>
</html>
"""

_HTML_PLACEHOLDER = re.compile(r"\{\{ (results|total|extracted) \}\}")

_EVIDENCE_HEADERS = ["Category", "Value", "Confidence", "Source", "Tool", "Found at",
                     "Content SHA-256"]


def _evidence_row(item: dict) -> list:
    """Returns one evidence record in the column order of ``_EVIDENCE_HEADERS``."""
    return [item["category"], item["value"], item.get("confidence", ""), item["source"],
            item.get("tool", ""), item.get("found_at", ""), item.get("content_sha256", "")]


def export_report_json(report: dict, output_path: str) -> None:
    """Writes a tool report to a JSON file inside DIR_REPORTS."""
    path = os.path.join(DIR_REPORTS, os.path.basename(output_path))
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=4, default=str)
        print_success(f"JSON saved → {path}")
    except OSError as e:
        print_error(f"I/O error exporting JSON: {e}")


class ResultsParser:
    """
    Data transformation layer for search result sets.
    """

    def __init__(self, results: list, extracted: list | None = None):
        """
        Args:
            results:   Search results.
            extracted: Values from a deep search, as dicts with ``category``,
                       ``value`` and ``source``. Leave as None for a plain
                       search; an empty list means a deep search found nothing.
        """
        self.results = results
        self.extracted = extracted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _output_path(self, filename: str) -> str:
        """Returns the absolute path inside DIR_REPORTS."""
        return os.path.join(DIR_REPORTS, os.path.basename(filename))

    def _extracted_html(self) -> str:
        """Renders the extracted-data section, or nothing for a plain search."""
        if self.extracted is None:
            return ""
        rows = []
        for item in self.extracted:
            source = item["source"]
            source_cell = html.escape(source)
            if source.startswith(("http://", "https://")):
                source_cell = (f'<a href="{html.escape(source, quote=True)}" target="_blank" '
                               f'rel="noopener noreferrer">{source_cell}</a>')
            rows.append(
                f'<tr><td>{html.escape(item["category"])}</td>'
                f'<td>{html.escape(item["value"])}</td>'
                f'<td>{html.escape(item.get("confidence", ""))}</td>'
                f'<td>{source_cell}</td>'
                f'<td>{html.escape(item.get("tool", ""))}</td>'
                f'<td>{html.escape(item.get("found_at", ""))}</td></tr>'
            )
        return (
            '<section class="extracted">'
            f'<h2>Extracted data ({len(self.extracted)})</h2>'
            '<table><thead><tr><th>Category</th><th>Value</th><th>Confidence</th>'
            '<th>Source</th><th>Tool</th><th>Found at</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            '</section>'
        )

    # ------------------------------------------------------------------
    # HTML export
    # ------------------------------------------------------------------

    def export_html(self, output_path: str) -> None:
        """
        Exports results into a self-contained, styled HTML report.
        """
        path = self._output_path(output_path)

        try:
            fragments = []
            for i, r in enumerate(self.results, 1):
                title = html.escape(r.get("title") or "No title")
                description = html.escape(r.get("description") or "No description")
                link_raw = r.get("link") or ""
                link_attr = html.escape(link_raw, quote=True) or "#"
                link_text = html.escape(link_raw) or "No link"
                fragments.append(
                    '<div class="result">'
                    f'<div class="index">Result {i}</div>'
                    f'<h5>{title}</h5>'
                    f'<p>{description}</p>'
                    f'<a href="{link_attr}" target="_blank" rel="noopener noreferrer">{link_text}</a>'
                    '</div>'
                )

            sections = {
                "results": "\n".join(fragments),
                "total": str(len(self.results)),
                "extracted": self._extracted_html(),
            }
            # A single pass, so placeholder text inside scraped data stays literal.
            report = _HTML_PLACEHOLDER.sub(lambda m: sections[m.group(1)], _HTML_TEMPLATE)

            with open(path, "w", encoding="utf-8") as f:
                f.write(report)

            print_success(f"HTML report saved → {path}")

        except IOError as e:
            print_error(f"I/O error exporting HTML: {e}")
        except Exception as e:
            print_error(f"Unexpected error exporting HTML: {e}")

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_csv(self, output_path: str) -> None:
        """
        Dumps results to a flat UTF-8 CSV file. A CSV holds one table, so a deep
        search's extracted values go to a companion ``<name>_extracted.csv``.
        """
        path = self._output_path(output_path)
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Title", "Description", "Link"])
                for i, r in enumerate(self.results, 1):
                    writer.writerow([
                        i,
                        r.get("title", ""),
                        r.get("description", ""),
                        r.get("link", ""),
                    ])
            print_success(f"CSV saved → {path}")

            if self.extracted is not None:
                stem, ext = os.path.splitext(path)
                extracted_path = f"{stem}_extracted{ext}"
                with open(extracted_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(_EVIDENCE_HEADERS)
                    for item in self.extracted:
                        writer.writerow(_evidence_row(item))
                print_success(f"Extracted data CSV saved → {extracted_path}")
        except IOError as e:
            print_error(f"I/O error exporting CSV: {e}")
        except Exception as e:
            print_error(f"Unexpected error exporting CSV: {e}")

    # ------------------------------------------------------------------
    # Excel export
    # ------------------------------------------------------------------

    def export_excel(self, output_path: str) -> None:
        """
        Generates a polished Excel .xlsx file with a "Results" sheet, plus an
        "Extracted" sheet for a deep search's extracted values.
        """
        path = self._output_path(output_path)
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Results"
            self._fill_sheet(
                ws,
                ["ID", "Title", "Description", "Link"],
                [[i, r.get("title", ""), r.get("description", ""), r.get("link", "")]
                 for i, r in enumerate(self.results, 1)],
                link_col=4,
                wrap_col=3,
                max_widths={1: 5, 2: 45, 3: 80, 4: 60},
            )

            if self.extracted is not None:
                self._fill_sheet(
                    wb.create_sheet("Extracted"),
                    _EVIDENCE_HEADERS,
                    [_evidence_row(item) for item in self.extracted],
                    link_col=4,
                    wrap_col=2,
                    max_widths={1: 25, 2: 60, 3: 12, 4: 60, 5: 16, 6: 26, 7: 20},
                )

            wb.save(path)
            print_success(f"Excel report saved → {path}")

        except Exception as e:
            print_error(f"Unexpected error exporting Excel: {e}")

    @staticmethod
    def _fill_sheet(ws, headers: list, rows: list, link_col: int, wrap_col: int,
                    max_widths: dict) -> None:
        """
        Writes a styled table into a worksheet:
        - Styled header row (dark background, white bold text)
        - Alternating row colours (white / light blue)
        - Freeze pane on the first row
        - Auto-fitted column widths
        - Clickable hyperlinks in ``link_col`` and wrapped text in ``wrap_col``
        - Thin borders on all cells
        """
        # ── Styles ────────────────────────────────────────────────
        header_fill   = PatternFill("solid", fgColor="1E3A5F")   # dark navy
        header_font   = Font(bold=True, color="FFFFFF", size=11)
        header_align  = Alignment(horizontal="center", vertical="center")

        row_fill_even = PatternFill("solid", fgColor="EAF2FB")   # light blue
        row_fill_odd  = PatternFill("solid", fgColor="FFFFFF")   # white
        row_font      = Font(size=10)
        link_font     = Font(size=10, color="1155CC", underline="single")

        thin = Side(style="thin", color="BFBFBF")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # ── Header row ────────────────────────────────────────────
        ws.append(headers)
        ws.row_dimensions[1].height = 22

        for cell in ws[1]:
            cell.font      = header_font
            cell.fill      = header_fill
            cell.alignment = header_align
            cell.border    = border

        # ── Freeze top row ────────────────────────────────────────
        ws.freeze_panes = "A2"

        # ── Data rows ─────────────────────────────────────────────
        for row_num, row in enumerate(rows, 2):
            fill = row_fill_even if row_num % 2 == 0 else row_fill_odd
            url  = row[link_col - 1]

            ws.append(row)
            ws.row_dimensions[row_num].height = 16

            for col_idx, cell in enumerate(ws[row_num], 1):
                # Scraped data is untrusted text, never spreadsheet formulas.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.fill   = fill
                cell.border = border
                cell.alignment = Alignment(
                    vertical="center",
                    wrap_text=(col_idx == wrap_col)
                )

                if col_idx == link_col and str(url).startswith(("http://", "https://")):
                    cell.hyperlink = url
                    cell.font = link_font
                else:
                    cell.font = row_font

        # ── Auto-fit column widths ────────────────────────────────
        for col_idx, col_cells in enumerate(ws.iter_cols(), 1):
            max_len = max(
                (len(str(cell.value)) if cell.value else 0)
                for cell in col_cells
            )
            # Cap at defined max to prevent unreasonably wide columns
            fitted = min(max_len + 4, max_widths.get(col_idx, 40))
            ws.column_dimensions[get_column_letter(col_idx)].width = fitted

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    def export_json(self, output_path: str) -> None:
        """
        Serialises results to a pretty-printed JSON file: the plain result list,
        or ``{"results": [...], "extracted": [...]}`` for a deep search.
        """
        path = self._output_path(output_path)
        payload = self.results
        if self.extracted is not None:
            payload = {"results": self.results, "extracted": self.extracted}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=4)
            print_success(f"JSON saved → {path}")
        except IOError as e:
            print_error(f"I/O error exporting JSON: {e}")
        except Exception as e:
            print_error(f"Unexpected error exporting JSON: {e}")

    # ------------------------------------------------------------------
    # Rich terminal table
    # ------------------------------------------------------------------

    def to_table(self) -> Table:
        """
        Returns a pre-styled Rich Table of the current result set.
        Used for non-interactive rendering in the terminal.
        """
        tbl = make_table(
            f"Results  [{THEME['ACCENT']}]{len(self.results)} found[/]",
            ("#",           THEME["DIM"]),
            ("Title",       "bold white"),
            ("Link",        THEME["LINK"]),
            ("Description", THEME["DIM"]),
            show_lines=True,
        )
        for i, r in enumerate(self.results, 1):
            desc = r.get("description", "")
            tbl.add_row(
                str(i),
                r.get("title", "N/A"),
                r.get("link",  "N/A"),
                (desc[:100] + "…") if len(desc) > 100 else desc,
            )
        return tbl
