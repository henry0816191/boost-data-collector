"""Library detail page renderer for dashboard HTML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boost_library_usage_dashboard.dashboard_html_common import (
    CHARTJS_VERSION,
    base_css,
    e,
    json_for_script,
    table_container,
    table_js,
    version_key,
)
from boost_library_usage_dashboard.utils import sanitize_library_name


def build_library_page(
    data: dict[str, Any], library_name: str, libraries_dir: Path
) -> None:
    """Build per-library HTML page."""
    lib_data = (data.get("libraries_page_data", {}) or {}).get(library_name, {})
    if not lib_data:
        return

    dependents = (lib_data.get("internal_dependents_data", {}) or {}).get(
        "table_data", []
    )
    dep_chart = (lib_data.get("internal_dependents_data", {}) or {}).get(
        "chart_data", {}
    )
    ext = (lib_data.get("external_consumers", {}) or {}).get("table_data", [])
    ext_chart = (lib_data.get("external_consumers", {}) or {}).get("chart_data", {})
    contrib = (lib_data.get("contribute_data", {}) or {}).get("table_data", [])
    commit_chart = (lib_data.get("contribute_data", {}) or {}).get("chart_data", {})
    overview = lib_data.get("over_view", {}) or {}
    headers_rows = [
        {"name": k, "count": v}
        for k, v in sorted(
            (overview.get("used_headers", {}) or {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )
    ]

    versions = sorted(list(dep_chart.keys()), key=version_key)
    dep_first = []
    dep_all = []
    for version in versions:
        entry = dep_chart.get(version, {})
        dep_first.append(entry.get("first_level", 0) if isinstance(entry, dict) else 0)
        dep_all.append(entry.get("all_deeper", 0) if isinstance(entry, dict) else 0)

    years = (
        sorted(str(y) for y in ext_chart.keys()) if isinstance(ext_chart, dict) else []
    )
    repo_counts = []
    by_created = []
    by_updated = []
    for y in years:
        yd = ext_chart.get(y, ext_chart.get(int(y), {}))
        if isinstance(yd, dict):
            repo_counts.append(yd.get("repos", 0))
            by_created.append(yd.get("by_created", 0))
            by_updated.append(yd.get("by_last_commit", 0))
        else:
            repo_counts.append(0)
            by_created.append(0)
            by_updated.append(0)

    commit_versions = (
        sorted(commit_chart.keys(), key=version_key)
        if isinstance(commit_chart, dict)
        else []
    )
    commit_counts = [commit_chart.get(v, 0) for v in commit_versions]

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(library_name)} - Boost Library Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_VERSION}/dist/chart.umd.min.js"></script>
  <style>{base_css()}</style>
</head>
<body>
  <div class="back-link"><a href="../index.html">← Back to Dashboard</a></div>
  <h1>📚 {e(library_name)}</h1>

  <div class="panel">
    <h2>Overview</h2>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:30px; align-items:start;">
      <div>
        <p style="color:#666;">{e(overview.get("description", ""))}</p>
        <table><tbody>
          <tr><td><strong>Created Version:</strong></td><td>{e(overview.get('created_version', 'N/A') or 'N/A')}</td></tr>
          <tr><td><strong>Most Recent Modified Version:</strong></td><td>{e(overview.get('last_updated_version', 'N/A') or 'N/A')}</td></tr>
          <tr><td><strong>Total Repositories:</strong></td><td>{int(overview.get('used_repo_count', 0) or 0):,}</td></tr>
          <tr><td><strong>Average New Repositories Per Year:</strong></td><td>{float(overview.get('average_used_repo_count', 0) or 0):.2f}</td></tr>
          <tr><td><strong>Most Recent Year Repository Count:</strong></td><td>{int((overview.get('last_year_used_repo_count', {}) or {}).get('count', 0) or 0):,}</td></tr>
          <tr><td><strong>Most Used Year:</strong></td><td>{e((overview.get('most_used_year', {}) or {}).get('year', 'N/A'))}</td></tr>
          <tr><td><strong>Average Stars:</strong></td><td>{int(overview.get('average_star', 0) or 0):,}</td></tr>
          <tr><td><strong>Activity Score:</strong></td><td>{float(overview.get('active_score', 0) or 0):.3f}</td></tr>
          <tr><td><strong>Internal Consumers:</strong></td><td>{int(overview.get('internal_consumers', 0) or 0):,}</td></tr>
          <tr><td><strong>Contributors in Most Recent Version:</strong></td><td>{int(overview.get('last_contributors', 0) or 0):,}</td></tr>
          <tr><td><strong>Total Contributors:</strong></td><td>{int(overview.get('overall_contributors', 0) or 0):,}</td></tr>
        </tbody></table>
      </div>
      <div>
        {table_container(
          title="Used Headers",
          table_id="table-headers",
          search_id="search-headers",
          info_id="info-headers",
          prev_id="prev-headers",
          next_id="next-headers",
          headers=[("Header", "name"), ("Times Included", "count")],
        )}
      </div>
    </div>
  </div>

  <div class="panel">
    <h2>Internal Consumers</h2>
    <div class="panel-row">
      <div>
        {table_container(
          title="Consumer Libraries",
          table_id="table-internal",
          search_id="search-internal",
          info_id="info-internal",
          prev_id="prev-internal",
          next_id="next-internal",
          headers=[("Library", "name"), ("Depth", "depth")],
        )}
      </div>
      <div class="chart-container"><canvas id="dependentsChart"></canvas></div>
    </div>
  </div>

  <div class="panel">
    <h2>External Consumers</h2>
    <div class="panel-row">
      <div>
        {table_container(
          title="External Repositories",
          table_id="table-external",
          search_id="search-external",
          info_id="info-external",
          prev_id="prev-external",
          next_id="next-external",
          headers=[("Repository", "name"), ("Stars", "stars"), ("Header Includes", "usage_count"), ("Created", "created_at"), ("Updated", "updated_at")],
        )}
      </div>
      <div class="chart-container"><canvas id="usageChart"></canvas></div>
    </div>
  </div>

  <div class="panel">
    <h2>Contribution</h2>
    <div class="panel-row">
      <div>
        {table_container(
          title="Contributors",
          table_id="table-contrib",
          search_id="search-contrib",
          info_id="info-contrib",
          prev_id="prev-contrib",
          next_id="next-contrib",
          headers=[("Version", "version"), ("Contributor", "person"), ("Commit Count", "commit_count")],
        )}
      </div>
      <div class="chart-container"><canvas id="commitChart"></canvas></div>
    </div>
  </div>

  <script>
    {table_js()}
    const headersRows = {json_for_script(headers_rows)};
    const internalRows = {json_for_script(dependents)};
    const externalRows = {json_for_script(ext)};
    const contribRows = {json_for_script(contrib)};
    const depVersions = {json_for_script(versions)};
    const depFirst = {json_for_script(dep_first)};
    const depAll = {json_for_script(dep_all)};
    const usageYears = {json_for_script(years)};
    const byCreated = {json_for_script(by_created)};
    const byUpdated = {json_for_script(by_updated)};
    const repoCounts = {json_for_script(repo_counts)};
    const commitVersions = {json_for_script(commit_versions)};
    const commitCounts = {json_for_script(commit_counts)};

    initDataTable({{
      data: headersRows, tableId:'table-headers', searchId:'search-headers',
      infoId:'info-headers', prevId:'prev-headers', nextId:'next-headers',
      defaultSortKey:'count', defaultSortAsc:false,
      columns:[{{key:'name',type:'text'}},{{key:'count',type:'number'}}],
      rowHtml:(r)=>`<tr><td>${{esc(r.name || '')}}</td><td>${{toNumber(r.count).toLocaleString()}}</td></tr>`
    }});
    initDataTable({{
      data: internalRows, tableId:'table-internal', searchId:'search-internal',
      infoId:'info-internal', prevId:'prev-internal', nextId:'next-internal',
      defaultSortKey:'depth', defaultSortAsc:true,
      columns:[{{key:'name',type:'text'}},{{key:'depth',type:'number'}}],
      rowHtml:(r)=>`<tr><td><a href="${{esc((r.name || '').replace(/[^\\w\\-.]/g,'_'))}}.html">${{esc(r.name || '')}}</a></td><td>${{toNumber(r.depth)}}</td></tr>`
    }});
    initDataTable({{
      data: externalRows, tableId:'table-external', searchId:'search-external',
      infoId:'info-external', prevId:'prev-external', nextId:'next-external',
      defaultSortKey:'stars', defaultSortAsc:false,
      columns:[{{key:'name',type:'text'}},{{key:'stars',type:'number'}},{{key:'usage_count',type:'number'}},{{key:'created_at',type:'date'}},{{key:'updated_at',type:'date'}}],
      rowHtml:(r)=>`<tr><td><a href="https://github.com/${{esc(r.name || '')}}" target="_blank">${{esc(r.name || '')}}</a></td><td>${{toNumber(r.stars).toLocaleString()}}</td><td>${{toNumber(r.usage_count).toLocaleString()}}</td><td>${{esc((r.created_at || '').toString().slice(0,10) || 'N/A')}}</td><td>${{esc((r.updated_at || '').toString().slice(0,10) || 'N/A')}}</td></tr>`
    }});
    initDataTable({{
      data: contribRows, tableId:'table-contrib', searchId:'search-contrib',
      infoId:'info-contrib', prevId:'prev-contrib', nextId:'next-contrib',
      defaultSortKey:'commit_count', defaultSortAsc:false,
      columns:[{{key:'version',type:'text'}},{{key:'person',type:'text'}},{{key:'commit_count',type:'number'}}],
      rowHtml:(r)=>`<tr><td>${{esc(r.version || '')}}</td><td>${{esc(r.person || '')}}</td><td>${{toNumber(r.commit_count).toLocaleString()}}</td></tr>`
    }});

    new Chart(document.getElementById('dependentsChart'), {{
      type:'bar',
      data: {{ labels: depVersions, datasets:[
        {{label:'Primary Consumers', data: depFirst, backgroundColor:'rgba(59,130,246,0.7)'}},
        {{label:'Transitive Consumers', data: depAll, backgroundColor:'rgba(16,185,129,0.7)'}}
      ] }},
      options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }} }} }}
    }});

    new Chart(document.getElementById('usageChart'), {{
      type:'bar',
      data: {{ labels: usageYears, datasets:[
        {{type:'line', label:'Created Repositories', data: repoCounts, borderColor:'rgba(255,99,132,0.8)', fill:false, yAxisID:'y1'}},
        {{label:'Header Includes (New Repos)', data: byCreated, backgroundColor:'rgba(54,162,235,0.6)'}},
        {{label:'Header Includes (Updated Repos)', data: byUpdated, backgroundColor:'rgba(75,192,192,0.6)'}}
      ] }},
      options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }}, y1: {{ beginAtZero:true, position:'right', grid: {{ drawOnChartArea:false }} }} }} }}
    }});

    new Chart(document.getElementById('commitChart'), {{
      type:'bar',
      data: {{ labels: commitVersions, datasets:[{{ label:'Commit Count', data: commitCounts, backgroundColor:'rgba(255,99,132,0.6)' }}] }},
      options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }} }} }}
    }});
  </script>
</body>
</html>
"""
    (libraries_dir / f"{sanitize_library_name(library_name)}.html").write_text(
        html_out,
        encoding="utf-8",
    )
