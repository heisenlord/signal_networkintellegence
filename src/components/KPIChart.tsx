import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, ChevronDown } from 'lucide-react';
import type { Entity, KPISeries } from '../types';
import { Badge, Empty, Value } from './ui';

export function KPIChart({ data, entityId, entities, onEntityChange, metric, onMetricChange }: {
  data?: KPISeries; entityId: string; entities: Entity[]; onEntityChange: (id: string) => void;
  metric: 'availability' | 'throughput_mbps'; onMetricChange: (metric: 'availability' | 'throughput_mbps') => void;
}) {
  const points = data?.points.map(p => ({ ...p, time: p.window.slice(11, 16) })) || [];
  const latest = points.at(-1);
  const first = points[0];
  const drop = latest?.availability != null && first?.availability != null ? latest.availability - first.availability : null;
  const cells = entities.filter(e => e.type === 'cell');
  return <section className="card kpi-card">
    <div className="card-head"><div><div className="eyebrow">KPI ENGINE</div><h2>Performance over time</h2></div><Badge tone={latest?.quality === 'complete' ? 'green' : 'amber'}>{latest?.quality === 'complete' ? 'Complete coverage' : 'Incomplete evidence'}</Badge></div>
    <div className="chart-toolbar"><div className="segment" aria-label="KPI metric"><button className={metric === 'availability' ? 'active' : ''} onClick={() => onMetricChange('availability')}>Availability</button><button className={metric === 'throughput_mbps' ? 'active' : ''} onClick={() => onMetricChange('throughput_mbps')}>Throughput</button></div>
      <label className="select-wrap small"><select aria-label="KPI entity" value={entityId} onChange={e => onEntityChange(e.target.value)}>{cells.map(e => <option key={e.id}>{e.id}</option>)}</select><ChevronDown size={12} /></label></div>
    <div className="chart-number"><strong><Value value={latest?.[metric]} suffix={metric === 'availability' ? '%' : ' Mbps'} /></strong>{metric === 'availability' && drop !== null && <span className="negative">{drop.toFixed(1)} pp <span>vs {first?.window.slice(11, 16)} baseline</span></span>}</div>
    {points.length ? <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{ left: -23, right: 15, top: 10, bottom: 0 }}>
      <defs><linearGradient id="kpiFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#339582" stopOpacity={0.18} /><stop offset="100%" stopColor="#339582" stopOpacity={0.01} /></linearGradient></defs>
      <CartesianGrid stroke="#edf0eb" vertical={false} strokeDasharray="3 3" />
      <XAxis dataKey="time" tick={{ fill: '#87918b', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={26} />
      <YAxis domain={metric === 'availability' ? [0, 100] : [0, 'auto']} tick={{ fill: '#87918b', fontSize: 10 }} tickLine={false} axisLine={false} />
      <Tooltip contentStyle={{ border: '1px solid #e2e8e1', borderRadius: 8, fontSize: 12 }} labelFormatter={l => `${l} UTC · 15-minute window`} formatter={(v, name) => [v == null ? 'Unavailable' : `${v}${metric === 'availability' ? '%' : ' Mbps'}`, name === 'availability' ? 'Availability' : 'Throughput']} />
      <ReferenceArea x1="09:45" x2="10:00" fill="#e9aa7b" fillOpacity={0.07} />
      <Area type="monotone" dataKey={metric} stroke="none" fill="url(#kpiFill)" connectNulls={false} tooltipType="none" />
      <Line type="monotone" dataKey={metric} stroke="#2b8c79" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} connectNulls={false} />
    </ComposedChart></ResponsiveContainer></div> : <Empty title="No cell measurements">Select a cell to view its performance history.</Empty>}
    <div className="chart-footer"><span><Activity size={12} />15-minute windows · availability-v1</span><span>Provisional · 2h watermark</span></div>
    {latest?.quality !== 'complete' && <div className="inline-note">{latest?.availability == null ? 'Incident-window values are absent. Missing data is not 0% availability.' : `Only ${Math.round((latest?.completeness || 0) * 100)}% of expected measurements arrived. Interpret with caution.`}</div>}
  </section>;
}
