"""Index page renderer for dashboard HTML."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from boost_library_usage_dashboard.dashboard_html_common import (
    CHARTJS_VERSION,
    base_css,
    e,
    json_for_script,
    table_container,
    table_js,
)
from boost_library_usage_dashboard.utils import sanitize_library_name


def build_index_page(data: dict[str, Any], output_dir: Path) -> None:
    """Build index.html dashboard page."""
    repos_by_year = data.get("repos_by_year", {})
    repos_by_version = data.get("repos_by_version", [])
    repos_by_year_boost_rate = data.get("repos_by_year_boost_rate", [])
    language_comparison_data = data.get("language_comparison_data", {})
    metrics_by_library = data.get("metrics_by_library", [])
    all_libraries_sorted = sorted(
        metrics_by_library,
        key=lambda lib: str(lib.get("name", "")).lower(),
    )
    top_repositories = data.get("top_repositories", {})

    top20_by_stars = top_repositories.get("top20_by_stars", [])
    top20_by_usage = top_repositories.get("top20_by_usage", [])
    top20_by_created = top_repositories.get("top20_by_created", [])

    sorted_years = sorted(repos_by_year.items(), key=lambda x: x[0])
    year_labels = [str(y) for y, _ in sorted_years]
    year_counts = [c for _, c in sorted_years]
    year_cumulative = []
    acc = 0
    for c in year_counts:
        acc += c
        year_cumulative.append(acc)

    version_labels = [
        row[0] if isinstance(row, list) else row.get("version", "")
        for row in repos_by_version
    ]
    version_counts = [
        row[1] if isinstance(row, list) else row.get("count", 0)
        for row in repos_by_version
    ]
    version_cumulative = []
    acc = 0
    for c in version_counts:
        acc += c
        version_cumulative.append(acc)

    boost_sorted = sorted(repos_by_year_boost_rate, key=lambda x: x.get("year", ""))
    boost_labels = [str(r.get("year", "")) for r in boost_sorted]
    boost_over_10 = [r.get("boost_over_10", 0) for r in boost_sorted]
    non_boost_over_10 = [
        max(0, r.get("over_10", 0) - r.get("boost_over_10", 0)) for r in boost_sorted
    ]
    boost_rate = []
    for r in boost_sorted:
        txt = str(r.get("boost_over_10_percentage", "0%")).replace("%", "").strip()
        try:
            boost_rate.append(float(txt))
        except ValueError:
            boost_rate.append(0.0)

    languages = sorted(language_comparison_data.keys())
    language_data = {}
    if languages:
        all_years = sorted(
            {y for lang in language_comparison_data.values() for y in lang.keys()}
        )
        for lang in languages:
            years = []
            all_counts = []
            stars10 = []
            percents = []
            for y in all_years:
                yd = language_comparison_data.get(lang, {}).get(y, {})
                all_c = yd.get("all", 0)
                s10 = yd.get("stars_10_plus", 0)
                pct = (s10 / all_c * 100) if all_c else 0.0
                years.append(str(y))
                all_counts.append(all_c)
                stars10.append(s10)
                percents.append(pct)
            language_data[lang] = {
                "years": years,
                "all_counts": all_counts,
                "stars_10_plus_counts": stars10,
                "percentages": percents,
            }

    library_overview_rows = []
    for lib in metrics_by_library:
        row = dict(lib)
        row["safe_name"] = sanitize_library_name(lib.get("name", ""))
        library_overview_rows.append(row)

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Boost Library Usage Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_VERSION}/dist/chart.umd.min.js"></script>
  <style>{base_css()}</style>
</head>
<body>
  <div style="margin-bottom: 10px;"><a href="../index.html" style="color: #666; text-decoration: none; font-size: 0.9rem;">← Back to Version Selector</a></div>
  <h1>📊 Boost Library Usage Dashboard</h1>
  <p style="text-align: center; color: #666;">Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

  <div class="panel"><h2>New Repositories Using Boost Libraries by Year</h2><div class="chart-container"><canvas id="reposByYearChart"></canvas></div></div>
  <div class="panel"><h2>C++ Repository Growth Analysis</h2><div class="chart-container"><canvas id="cppRepoAnalysisChart"></canvas></div></div>
  <div class="panel">
    <h2>Language Comparison by Year</h2>
    <div style="margin-bottom: 15px;">
      <label for="language-selector" style="margin-right: 10px; font-weight: 600;">Select Language:</label>
      <select id="language-selector">{''.join(f"<option value='{e(lang)}'>{e(lang)}</option>" for lang in languages)}</select>
    </div>
    <div class="chart-container"><canvas id="languageComparisonChart"></canvas></div>
  </div>
  <div class="panel"><h2>New Repositories by Boost Version</h2><div class="chart-container"><canvas id="reposByVersionChart"></canvas></div></div>

  <div class="panel">
    <h2>Library Overview</h2>
    {table_container(
      title="Libraries",
      table_id="table-library-overview",
      search_id="search-library-overview",
      info_id="info-library-overview",
      prev_id="prev-library-overview",
      next_id="next-library-overview",
      headers=[
        ("Library", "name"),
        ("Created Version", "created_version"),
        ("Repo Count", "repo_count"),
        ("Total Usage", "total_usage"),
        ("Recent Usage", "recent_usage"),
        ("Activity Score", "activity_score"),
        ("Average Stars", "average_stars"),
      ],
    )}
  </div>

  <div class="panel">
    <h2>Top 20 Repositories by Different Metrics</h2>
    <div style="margin-bottom: 15px;">
      <button class="tab-button active" data-tab="stars">By Stars</button>
      <button class="tab-button" data-tab="usage">By Total Boost Usage</button>
      <button class="tab-button" data-tab="created">By Last Created</button>
    </div>
    <div id="tab-stars" class="tab-content" style="display:block;">
      {table_container(
        title="Top Repositories by Stars",
        table_id="table-top-stars",
        search_id="search-top-stars",
        info_id="info-top-stars",
        prev_id="prev-top-stars",
        next_id="next-top-stars",
        headers=[("Repository", "repo_name"), ("Stars", "stars"), ("Used", "usage_count"), ("Created", "created_at")],
      )}
    </div>
    <div id="tab-usage" class="tab-content" style="display:none;">
      {table_container(
        title="Top Repositories by Total Boost Usage",
        table_id="table-top-usage",
        search_id="search-top-usage",
        info_id="info-top-usage",
        prev_id="prev-top-usage",
        next_id="next-top-usage",
        headers=[("Repository", "repo_name"), ("Stars", "stars"), ("Used", "usage_count"), ("Created", "created_at")],
      )}
    </div>
    <div id="tab-created" class="tab-content" style="display:none;">
      {table_container(
        title="Top Repositories by Last Created",
        table_id="table-top-created",
        search_id="search-top-created",
        info_id="info-top-created",
        prev_id="prev-top-created",
        next_id="next-top-created",
        headers=[("Repository", "repo_name"), ("Stars", "stars"), ("Used", "usage_count"), ("Created", "created_at")],
      )}
    </div>
  </div>

  <div class="panel">
    <h2>All Libraries</h2>
    <p style="color:#666;margin-top:0;">Browse all Boost libraries. Click on any library name to view detailed statistics.</p>
    <div class="library-grid">{''.join(f"<div class='library-item'><a href='libraries/{e(sanitize_library_name(lib.get('name','')))}.html'>{e(lib.get('name',''))}</a></div>" for lib in all_libraries_sorted)}</div>
  </div>

  <script>
    {table_js()}
    const yearLabels = {json_for_script(year_labels)};
    const yearCounts = {json_for_script(year_counts)};
    const yearCum = {json_for_script(year_cumulative)};
    const versionLabels = {json_for_script(version_labels)};
    const versionCounts = {json_for_script(version_counts)};
    const versionCum = {json_for_script(version_cumulative)};
    const boostLabels = {json_for_script(boost_labels)};
    const boostOver10 = {json_for_script(boost_over_10)};
    const nonBoostOver10 = {json_for_script(non_boost_over_10)};
    const boostRate = {json_for_script(boost_rate)};
    const languageData = {json_for_script(language_data)};
    const allLanguages = {json_for_script(languages)};
    const tableLibraryOverview = {json_for_script(library_overview_rows)};
    const tableTopStars = {json_for_script(top20_by_stars)};
    const tableTopUsage = {json_for_script(top20_by_usage)};
    const tableTopCreated = {json_for_script(top20_by_created)};

    function dualChart(id, labels, bars, lines, barLabel, lineLabel) {{
      new Chart(document.getElementById(id), {{
        type: 'bar',
        data: {{
          labels: labels,
          datasets: [
            {{ type:'bar', label: barLabel, data: bars, backgroundColor:'rgba(54,162,235,0.6)', borderColor:'rgba(54,162,235,1)', borderWidth:2 }},
            {{ type:'line', label: lineLabel, data: lines, borderColor:'rgba(255,99,132,0.8)', borderWidth:3, fill:false, yAxisID:'y1' }}
          ]
        }},
        options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }}, y1: {{ beginAtZero:true, position:'right', grid: {{ drawOnChartArea:false }} }} }} }}
      }});
    }}
    dualChart('reposByYearChart', yearLabels, yearCounts, yearCum, 'Year Total', 'Cumulative Total');
    dualChart('reposByVersionChart', versionLabels, versionCounts, versionCum, 'Version Total', 'Cumulative Total');

    new Chart(document.getElementById('cppRepoAnalysisChart'), {{
      type: 'bar',
      data: {{
        labels: boostLabels,
        datasets: [
          {{ type:'bar', label:'Boost Repos >10 Stars', data: boostOver10, backgroundColor:'rgba(255,99,132,0.6)', stack:'s1' }},
          {{ type:'bar', label:'Non-Boost Repos >10 Stars', data: nonBoostOver10, backgroundColor:'rgba(75,192,192,0.6)', stack:'s1' }},
          {{ type:'line', label:'Boost Usage Rate (%)', data: boostRate, borderColor:'rgba(153,102,255,0.8)', fill:false, yAxisID:'y1' }}
        ]
      }},
      options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }}, y1: {{ beginAtZero:true, position:'right', grid: {{ drawOnChartArea:false }} }} }} }}
    }});

    let langChart = null;
    function updateLanguageChart(lang) {{
      const d = languageData[lang];
      if (!d) return;
      const nonStars = d.all_counts.map((all, idx) => all - d.stars_10_plus_counts[idx]);
      if (langChart) langChart.destroy();
      langChart = new Chart(document.getElementById('languageComparisonChart'), {{
        type:'bar',
        data: {{ labels:d.years, datasets:[
          {{type:'bar',label:'All Repos',data:nonStars,backgroundColor:'rgba(75,192,192,0.6)',stack:'s1'}},
          {{type:'bar',label:'Repos >10 Stars',data:d.stars_10_plus_counts,backgroundColor:'rgba(255,99,132,0.6)',stack:'s1'}},
          {{type:'line',label:'Percentage (%)',data:d.percentages,borderColor:'rgba(153,102,255,0.8)',fill:false,yAxisID:'y1'}}
        ]}},
        options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }}, y1: {{ beginAtZero:true, position:'right', grid: {{ drawOnChartArea:false }} }} }} }}
      }});
    }}
    const langSel = document.getElementById('language-selector');
    if (langSel) {{
      langSel.addEventListener('change', (e) => updateLanguageChart(e.target.value));
      if (allLanguages.length) updateLanguageChart(allLanguages[0]);
    }}

    initDataTable({{
      data: tableLibraryOverview, tableId: 'table-library-overview', searchId: 'search-library-overview',
      infoId: 'info-library-overview', prevId: 'prev-library-overview', nextId: 'next-library-overview',
      defaultSortKey: 'name', defaultSortAsc: true,
      columns: [
        {{key:'name', type:'text'}}, {{key:'created_version', type:'text'}},
        {{key:'repo_count', type:'number'}}, {{key:'total_usage', type:'number'}},
        {{key:'recent_usage', type:'number'}}, {{key:'activity_score', type:'number'}},
        {{key:'average_stars', type:'number'}}
      ],
      rowHtml: (r) => `<tr><td><a href="libraries/${{esc(r.safe_name)}}.html">${{esc(r.name || '')}}</a></td><td>${{esc(r.created_version || '')}}</td><td>${{toNumber(r.repo_count).toLocaleString()}}</td><td>${{toNumber(r.total_usage).toLocaleString()}}</td><td>${{toNumber(r.recent_usage).toLocaleString()}}</td><td>${{esc(Number(r.activity_score || 0).toFixed(3))}}</td><td>${{toNumber(r.average_stars).toLocaleString()}}</td></tr>`
    }});

    const topColumns = [{{key:'repo_name', type:'text'}}, {{key:'stars', type:'number'}}, {{key:'usage_count', type:'number'}}, {{key:'created_at', type:'date'}}];
    const topRow = (r) => `<tr><td><a href="https://github.com/${{esc(r.repo_name || '')}}" target="_blank">${{esc(r.repo_name || '')}}</a></td><td>${{toNumber(r.stars).toLocaleString()}}</td><td>${{toNumber(r.usage_count).toLocaleString()}}</td><td>${{esc((r.created_at || '').toString().slice(0,10) || 'N/A')}}</td></tr>`;
    initDataTable({{ data: tableTopStars, tableId:'table-top-stars', searchId:'search-top-stars', infoId:'info-top-stars', prevId:'prev-top-stars', nextId:'next-top-stars', defaultSortKey:'stars', defaultSortAsc:false, columns: topColumns, rowHtml: topRow }});
    initDataTable({{ data: tableTopUsage, tableId:'table-top-usage', searchId:'search-top-usage', infoId:'info-top-usage', prevId:'prev-top-usage', nextId:'next-top-usage', defaultSortKey:'usage_count', defaultSortAsc:false, columns: topColumns, rowHtml: topRow }});
    initDataTable({{ data: tableTopCreated, tableId:'table-top-created', searchId:'search-top-created', infoId:'info-top-created', prevId:'prev-top-created', nextId:'next-top-created', defaultSortKey:'created_at', defaultSortAsc:false, columns: topColumns, rowHtml: topRow }});

    document.querySelectorAll('.tab-button').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
        btn.classList.add('active');
        document.getElementById(`tab-${{btn.dataset.tab}}`).style.display = 'block';
      }});
    }});
  </script>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html_out, encoding="utf-8")
