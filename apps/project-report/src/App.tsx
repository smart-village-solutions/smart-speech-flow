import { useEffect, useMemo, useState } from 'react';
import reportData from './data/project-status.json';
import { deriveMilestones, flattenWorkPackages, matchesFilters, type Filters } from './lib/report-model';
import { type ProjectStatusReport, validateProjectStatusReport } from './lib/project-status';
import { parseFilters, stringifyFilters } from './lib/url-state';

const report = reportData as ProjectStatusReport;
const validationErrors = validateProjectStatusReport(report);
const healthLabels = { on_track: 'Im Plan', needs_attention: 'Aufmerksamkeit', at_risk: 'Gefährdet', blocked: 'Blockiert' };
const complexityLabels = { low: 'Niedrig', medium: 'Mittel', high: 'Hoch', very_high: 'Sehr hoch' };

function Progress({ value }: { value: number }) {
  return <div className="progress" aria-label={`${value} Prozent Fortschritt`}><span style={{ width: `${value}%` }} /><b>{value}%</b></div>;
}

export default function App() {
  const [filters, setFilters] = useState<Filters>(() => parseFilters());
  const [details, setDetails] = useState<string | null>(null);
  const workPackages = useMemo(() => flattenWorkPackages(report).filter((item) => matchesFilters(item, filters)), [filters]);
  const milestones = useMemo(() => deriveMilestones(report, workPackages, filters), [workPackages, filters]);

  useEffect(() => {
    const query = stringifyFilters(filters);
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
  }, [filters]);
  useEffect(() => {
    const onPopState = () => setFilters(parseFilters());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  if (validationErrors.length) return <main className="error"><h1>Ungültiger Projektstatus</h1><ul>{validationErrors.map((error) => <li key={error}>{error}</li>)}</ul></main>;
  const update = (key: keyof Filters, value: string) => setFilters((current) => ({ ...current, [key]: value }));

  return <main>
    <header>
      <p className="eyebrow">Smart Speech Flow · interner Snapshot</p>
      <h1>Projektbericht</h1>
      <p>Stand {report.meta.updatedAt} · Version {report.meta.version}</p>
    </header>
    <section className="toolbar" aria-label="Bericht filtern">
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={filters.view === 'milestones'} onClick={() => update('view', 'milestones')}>Meilensteine</button>
        <button role="tab" aria-selected={filters.view === 'work-packages'} onClick={() => update('view', 'work-packages')}>Arbeitspakete</button>
      </div>
      <label>Suche<input value={filters.q} onChange={(event) => update('q', event.target.value)} placeholder="ID, Titel, Bereich …" /></label>
      <label>Meilenstein<select value={filters.milestone} onChange={(event) => update('milestone', event.target.value)}><option value="all">Alle Meilensteine</option>{report.milestones.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
      <label>Status<select value={filters.status} onChange={(event) => update('status', event.target.value)}><option value="all">Alle Status</option>{Object.entries(report.statusModel).map(([id, value]) => <option value={id} key={id}>{value}% · {id}</option>)}</select></label>
      <label>Priorität<select value={filters.priority} onChange={(event) => update('priority', event.target.value)}><option value="all">Alle Prioritäten</option>{Object.entries(report.priorityModel).map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label>
    </section>
    {filters.view === 'milestones' ? <section className="cards" aria-label="Meilensteine">{milestones.map((item) => <a className="card card-link" key={item.id} href={`?view=work-packages&milestone=${encodeURIComponent(item.id)}`} aria-label={`${item.title}: Arbeitspakete anzeigen`}><div className="card-title"><span>{item.id}</span><span className={`health ${item.health}`}>{healthLabels[item.health]}</span></div><h2>{item.title}</h2><Progress value={item.progress} /><dl><div><dt>Komplexität</dt><dd>{complexityLabels[item.complexity]}</dd></div><div><dt>Arbeitspakete</dt><dd>{item.workPackageCount}</dd></div></dl><span className="card-action">Arbeitspakete anzeigen →</span></a>)}</section> : <section className="table-wrap"><table><thead><tr><th>ID</th><th>Arbeitspaket</th><th>Bereich</th><th>Meilenstein</th><th>Priorität</th><th>Status</th><th>Warnstufe</th><th>Komplexität</th><th>Details</th></tr></thead><tbody>{workPackages.map((item) => <><tr key={item.id}><td>{item.id}</td><td>{item.title}</td><td>{item.area}</td><td>{item.milestoneId}</td><td>{report.priorityModel[item.priority]}</td><td>{item.progress}% · {item.status}</td><td><span className={`health ${item.health}`}>{healthLabels[item.health]}</span></td><td>{complexityLabels[item.complexity]}</td><td>{item.featureSummary && <button className="link" onClick={() => setDetails(details === item.id ? null : item.id)} aria-expanded={details === item.id}>Details</button>}</td></tr>{details === item.id && <tr className="details"><td colSpan={9}><p>{item.featureSummary}</p>{item.dependsOn.length > 0 && <p><b>Abhängig von:</b> {item.dependsOn.join(', ')}</p>}<DetailList title="Akzeptanzkriterien" entries={item.acceptanceCriteria} /><DetailList title="To-dos" entries={item.todos} /></td></tr>}</>)}</tbody></table></section>}
    <footer>Quelle: {report.meta.source}. Die Darstellung ist schreibgeschützt und bezieht keine Live-Daten.</footer>
  </main>;
}

function DetailList({ title, entries }: { title: string; entries?: string[] }) {
  return entries?.length ? <><h3>{title}</h3><ul>{entries.map((entry) => <li key={entry}>{entry}</li>)}</ul></> : null;
}
