/**
 * Read-only PM map from the Ark Time Review page: the PM filter's options, and for each PM the
 * jobs and customers their rows carry in the loaded date range. Run the whole file through
 * javascript_tool on the TimeReview page after the grid has loaded a range (a few months is
 * enough). It changes nothing on the page.
 * Returns arrays, because the browser tool's output filter blocks some key=value strings.
 */
function timeReviewPmSnapshot() {
  const widget = id => kendo.widgetInstance($('#' + id));
  const pmFilter = widget('PMDropDownListFilter');
  const textField = pmFilter && pmFilter.options.dataTextField;
  const pmOptions = pmFilter
    ? pmFilter.dataSource.data().toJSON().map(x => (textField ? x[textField] : x.Item2 || x.Text || x.Name))
        .filter(name => name && !/^select/i.test(name))
    : [];
  const rows = widget('grid').dataSource.view().toJSON().flatMap(group => (group.items ? group.items : [group]));
  const byPm = {};
  rows.forEach(row => {
    if (!row.PMName) return;
    const entry = byPm[row.PMName] || (byPm[row.PMName] = { jobs: {}, customers: {}, rows: 0 });
    entry.rows += 1;
    if (row.JobCardName) entry.jobs[row.JobCardName] = (entry.jobs[row.JobCardName] || 0) + 1;
    if (row.CustomerName) entry.customers[row.CustomerName] = (entry.customers[row.CustomerName] || 0) + 1;
  });
  return {
    pm_options: pmOptions,
    pm_columns: ['pm', 'rows', 'jobs', 'customers'],
    pms: Object.entries(byPm).map(([name, e]) => [name, e.rows, Object.keys(e.jobs), Object.keys(e.customers)]),
    rows_read: rows.length,
  };
}

timeReviewPmSnapshot();
