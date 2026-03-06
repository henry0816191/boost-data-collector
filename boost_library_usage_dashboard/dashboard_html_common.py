"""Shared helpers for dashboard HTML rendering."""

from __future__ import annotations

import html
import json
from typing import Any

CHARTJS_VERSION = "4.4.0"


def e(value: Any) -> str:
    """HTML-escape any value for safe template interpolation."""
    return html.escape(str(value), quote=True)


def json_for_script(value: Any) -> str:
    """Serialize value to JSON safe for embedding inside a <script> element.

    Escapes </ so that string content cannot break out of the script tag.
    """
    raw = json.dumps(value, ensure_ascii=False)
    return (
        raw.replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .replace("</", r"\u003c/")
    )


def version_key(version: str) -> tuple[int, int, int]:
    """Sort key for semantic-ish versions like '1.85.0'. Delegates to utils._version_tuple."""
    from boost_library_usage_dashboard.utils import _version_tuple

    return _version_tuple(version)


def base_css() -> str:
    """Shared CSS for index and library pages."""
    return """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  max-width: 1600px; margin: 0 auto; padding: 30px 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
}
h1 { text-align: center; color: #fff; font-size: 2.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.2); }
.panel { background: #fff; padding: 30px; margin: 25px 0; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.08); }
.panel h2 { margin-top: 0; margin-bottom: 20px; color: #1a202c; font-size: 1.6em; border-bottom: 3px solid #667eea; padding-bottom: 15px; }
.panel-row { display: grid; grid-template-columns: 1.2fr 1fr; gap: 20px; align-items: start; }
.chart-container { margin: 25px 0; height: 450px; position: relative; background: #fafafa; border-radius: 8px; padding: 15px; border: 1px solid #e2e8f0; }
canvas { width: 100% !important; height: 100% !important; display: block; }
table { width: 100%; border-collapse: collapse; margin: 20px 0; }
th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
th { background-color: #f0f0f0; font-weight: 600; }
a { color: #0066cc; text-decoration: none; } a:hover { text-decoration: underline; }
.sortable { cursor: pointer; user-select: none; }
.sort-indicator { margin-left: 5px; color: #666; }
.table-controls { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.table-controls input { padding: 8px; border: 1px solid #ddd; border-radius: 4px; width: 260px; }
.pagination { display: flex; gap: 8px; align-items: center; }
.pagination button { padding: 6px 12px; border: 1px solid #ddd; border-radius: 4px; background: #fff; cursor: pointer; }
.pagination button:disabled { opacity: .5; cursor: not-allowed; }
.library-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-top: 20px; }
.library-item { padding: 12px 16px; border: 2px solid #e2e8f0; border-radius: 8px; background: #f7fafc; text-align: center; }
.tab-button { padding: 10px 20px; margin-right: 5px; cursor: pointer; border: 1px solid #ddd; border-radius: 4px 4px 0 0; background: #fff; font-weight: 600; }
.tab-button.active { background: #f5f5f5; }
.back-link a { color: rgba(255,255,255,0.95); font-weight: 500; padding: 8px 16px; background: rgba(255,255,255,0.15); border-radius: 6px; }
"""


def table_container(
    *,
    title: str,
    table_id: str,
    search_id: str,
    info_id: str,
    prev_id: str,
    next_id: str,
    headers: list[tuple[str, str]],
) -> str:
    """Render generic table controls + sortable table skeleton."""
    headers_html = "".join(
        f"<th><button type='button' class='sortable' data-key='{e(key)}' aria-label='Sort by {e(label)}'>{e(label)} <span class='sort-indicator'>↕</span></button></th>"
        for label, key in headers
    )
    return f"""
<h3>{e(title)}</h3>
<div class="table-controls">
  <div><label for="{e(search_id)}">Search:</label> <input id="{e(search_id)}" type="text" placeholder="Filter rows..."></div>
  <div class="pagination">
    <span id="{e(info_id)}">Showing 0-0 of 0</span>
    <button id="{e(prev_id)}">Previous</button>
    <button id="{e(next_id)}">Next</button>
  </div>
</div>
<table id="{e(table_id)}"><thead><tr>{headers_html}</tr></thead><tbody></tbody></table>
"""


def table_js() -> str:
    """Common client-side data-table behavior for all pages."""
    return """
function toNumber(v){ if (v === null || v === undefined || v === '') return 0; const n = Number(v); return Number.isFinite(n) ? n : 0; }
function toText(v){ return (v ?? '').toString().toLowerCase(); }
function toDate(v){ if(!v) return 0; const t = Date.parse(v); return Number.isFinite(t) ? t : 0; }
function esc(s){ if (s == null || s === undefined) return ''; const t = String(s); return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

function initDataTable(cfg){
  const pageSize = 10;
  const data = [...cfg.data];
  let filtered = [...data];
  let page = 1;
  let sortKey = cfg.defaultSortKey || cfg.columns[0].key;
  let sortAsc = cfg.defaultSortAsc ?? false;

  const table = document.getElementById(cfg.tableId);
  const tbody = table.querySelector('tbody');
  const info = document.getElementById(cfg.infoId);
  const prev = document.getElementById(cfg.prevId);
  const next = document.getElementById(cfg.nextId);
  const search = document.getElementById(cfg.searchId);

  function sortValue(row, col){
    const v = row[col.key];
    if(col.type === 'number') return toNumber(v);
    if(col.type === 'date') return toDate(v);
    return toText(v);
  }
  function applyFilter(){
    const term = toText(search?.value || '');
    if(!term){ filtered = [...data]; return; }
    filtered = data.filter(row => cfg.columns.some(c => toText(row[c.key]).includes(term)));
  }
  function applySort(){
    const col = cfg.columns.find(c => c.key === sortKey) || cfg.columns[0];
    filtered.sort((a,b) => {
      const av = sortValue(a,col), bv = sortValue(b,col);
      if(av < bv) return sortAsc ? -1 : 1;
      if(av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
  }
  function updateIndicators(){
    table.querySelectorAll('.sortable').forEach(th => {
      const indicator = th.querySelector('.sort-indicator');
      if(!indicator) return;
      if(th.dataset.key === sortKey) indicator.textContent = sortAsc ? '↑' : '↓';
      else indicator.textContent = '↕';
    });
  }
  function render(){
    applyFilter();
    applySort();
    const total = filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if(page > totalPages) page = totalPages;
    const start = (page - 1) * pageSize;
    const end = Math.min(start + pageSize, total);
    tbody.innerHTML = filtered.slice(start, end).map(cfg.rowHtml).join('');
    info.textContent = total ? `Showing ${start + 1}-${end} of ${total}` : 'No data available';
    prev.disabled = page <= 1;
    next.disabled = page >= totalPages;
    updateIndicators();
  }

  table.querySelectorAll('.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if(sortKey === key) sortAsc = !sortAsc;
      else { sortKey = key; sortAsc = true; }
      page = 1; render();
    });
  });
  if(search) search.addEventListener('input', () => { page = 1; render(); });
  prev.addEventListener('click', () => { if(page > 1){ page -= 1; render(); } });
  next.addEventListener('click', () => { page += 1; render(); });
  render();
}
"""
