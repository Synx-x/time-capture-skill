/**
 * Read-only snapshot of the Ark Time Capture page: the day's captured entries, the live
 * job list and the category list. Run the whole file through javascript_tool on the
 * TimeCapture page. It changes nothing on the page.
 * Rows come back as arrays because the browser tool's output filter blocks some
 * key=value and URL-shaped strings.
 */
function timeCaptureSnapshot() {
  const widget = id => kendo.widgetInstance($('#' + id));
  const grid = widget('grid');
  const headers = grid.thead.find('th').map((i, th) => $(th).text().trim()).get();
  const col = name => headers.findIndex(h => h.startsWith(name));
  const startCol = col('Start');
  const endCol = col('End');
  const to24 = text => {
    const match = /(\d{1,2}):(\d{2})\s*(AM|PM)/i.exec(text || '');
    if (!match) return text;
    let hours24 = Number(match[1]) % 12;
    if (match[3].toUpperCase() === 'PM') hours24 += 12;
    return String(hours24).padStart(2, '0') + ':' + match[2];
  };
  const entries = grid.items().toArray().map(tr => {
    const row = grid.dataItem(tr);
    const cells = $(tr).children('td');
    const adoProject = (row.LinkToWorkItem || '').split('/_')[0].split('/').slice(-1)[0];
    return [
      to24(cells.eq(startCol).text().trim()),
      to24(cells.eq(endCol).text().trim()),
      row.CategoryDescription,
      row.JobCardID,
      row.JobCardName,
      row.VsoTaskID,
      row.VsoTaskDescription,
      row.IsBillable,
      row.Description,
      decodeURIComponent(adoProject || ''),
    ];
  });
  return {
    capture_for: widget('EmployeeID').text().trim(),
    date: kendo.toString(widget('Date').value(), 'yyyy-MM-dd'),
    entry_columns: ['start', 'end', 'category', 'job_id', 'job', 'vso_id', 'vso', 'billable',
                    'description', 'ado_project'],
    entries,
    job_columns: ['id', 'name'],
    jobs: widget('JobCardID').dataSource.data().map(x => [x.Item1, x.Item2]),
    category_columns: ['id', 'name', 'takes_job', 'default_description', 'clickup_linked'],
    categories: widget('Category').dataSource.data().map(x => [x.Item1, x.Item2.trim(), String(x.Item3) === '1', x.Item4, x.Item5 === true]),
  };
}

timeCaptureSnapshot();
