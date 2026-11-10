import { useEffect, useMemo } from 'react';
import { Background, BackgroundVariant, Controls, Handle, MarkerType, Position, ReactFlow, useNodesState, type Node, type NodeProps } from '@xyflow/react';
import dagre from 'dagre';
import { Antenna, Building2, Cable, Layers3, RadioTower, ScanLine } from 'lucide-react';
import type { Entity, Topology } from '../types';
import { Badge, Button } from './ui';
import '@xyflow/react/dist/style.css';

const icons: Record<string, typeof RadioTower> = { cell: Antenna, node: RadioTower, site: Building2, transport: Cable, service: Layers3 };
type NetworkNode = Node<{ entity: Entity; highlighted: boolean; historical: boolean }, 'network'>;

function NetworkEntity({ data, selected }: NodeProps<NetworkNode>) {
  const Icon = icons[data.entity.type] || RadioTower;
  const status = data.historical ? 'healthy' : data.entity.status;
  return <div className={`network-node ${status} ${selected ? 'is-selected' : ''} ${data.highlighted ? 'in-path' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <div className={`node-icon ${data.entity.type}`}><Icon size={17} strokeWidth={1.7} /></div>
    <div className="node-copy"><strong>{data.entity.id}</strong><span>{data.entity.name}</span></div>
    <span className={`status-dot ${status}`} />
    <Handle type="source" position={Position.Right} />
  </div>;
}
const nodeTypes = { network: NetworkEntity };
const incidentIds = new Set(['TRANS-01', 'SITE-01', 'SITE-02', 'NODE-01', 'NODE-02', 'CELL-101', 'CELL-102', 'CELL-201', 'CELL-202', 'SVC-01']);

export function TopologyGraph({ data, selected, onSelect, highlighted = [], full, onFullChange, historical }: {
  data: Topology; selected: string; onSelect: (id: string) => void; highlighted?: string[]; full: boolean; onFullChange: (value: boolean) => void; historical: boolean;
}) {
  const layout = useMemo(() => {
    const entities = data.entities.filter(e => full || incidentIds.has(e.id));
    const ids = new Set(entities.map(e => e.id));
    const relations = data.relationships.filter(e => ids.has(e.source) && ids.has(e.target));
    const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
    graph.setGraph({ rankdir: 'LR', nodesep: 25, ranksep: 65, marginx: 16, marginy: 16 });
    entities.forEach(e => graph.setNode(e.id, { width: 166, height: 58 }));
    relations.forEach(e => graph.setEdge(e.target, e.source));
    dagre.layout(graph);
    const marked = new Set(highlighted);
    return {
      nodes: entities.map(e => ({ id: e.id, type: 'network' as const, position: { x: graph.node(e.id).x - 83, y: graph.node(e.id).y - 29 },
        data: { entity: e, highlighted: marked.has(e.id), historical }, selected: e.id === selected })),
      edges: relations.map(e => {
        const affected = !historical && ['TRANS-01', 'NODE-01', 'NODE-02', 'CELL-101', 'CELL-102', 'CELL-201', 'CELL-202'].includes(e.source) && ['TRANS-01', 'NODE-01', 'NODE-02'].includes(e.target);
        return { id: e.id, source: e.target, target: e.source, type: 'smoothstep', animated: affected,
          style: { stroke: affected ? '#d9917b' : '#bdcdc7', strokeWidth: marked.has(e.source) && marked.has(e.target) ? 2.5 : 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: affected ? '#d9917b' : '#bdcdc7', width: 12, height: 12 } };
      }),
    };
  }, [data, full, highlighted, historical, selected]);
  const [nodes, setNodes, onNodesChange] = useNodesState<NetworkNode>(layout.nodes);
  useEffect(() => setNodes(layout.nodes), [layout.nodes, setNodes]);
  return <section className="card topology-card">
    <div className="card-head"><div><div className="eyebrow">TOPOLOGY ENGINE</div><h2>Connected network <Badge tone="neutral">{full ? data.entities.length : layout.nodes.length} entities</Badge></h2></div>
      <Button variant="outline" size="sm" onClick={() => onFullChange(!full)}><ScanLine size={14} />{full ? 'Incident cluster' : 'Full network'}</Button></div>
    <div className="graph-meta"><span><span className="tiny-dot" />{historical ? 'Before incident · v11' : 'Incident snapshot · v12'}</span><span>Drag to explore · click an entity</span></div>
    <div className="graph-canvas" aria-label="Interactive network topology">
      <ReactFlow key={`${full}-${historical}`} nodes={nodes} edges={layout.edges} onNodesChange={onNodesChange} nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)} fitView fitViewOptions={{ padding: 0.16 }} minZoom={0.03} maxZoom={1.8}
        nodesConnectable={false} deleteKeyCode={null} proOptions={{ hideAttribution: false }}>
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#d3dfd9" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
    <div className="graph-legend"><span><i className="status-dot healthy" />Healthy</span><span><i className="status-dot critical" />Critical</span><span><i className="status-dot degraded" />Degraded</span><span><i className="status-dot unknown" />Missing data</span><span className="legend-note">Arrows show dependency impact</span></div>
  </section>;
}
