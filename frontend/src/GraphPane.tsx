import { Background, Controls, Handle, MarkerType, Position, ReactFlow } from '@xyflow/react'
import type { Edge as FlowEdge, Node, NodeProps } from '@xyflow/react'
import { useMemo } from 'react'

import { layoutGraph } from './layout'
import type { Graph } from './types'

export type ExperimentFlowNode = Node<
  { title: string; expId: string; commit: string },
  'experiment'
>

function ExperimentNode({ data, selected }: NodeProps<ExperimentFlowNode>) {
  return (
    <div className={`exp-node${selected ? ' exp-node--selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="exp-node__title">{data.title}</div>
      <div className="exp-node__id">{data.expId}</div>
      <div className="exp-node__commit" title={`commit ${data.commit}`}>
        {data.commit.slice(0, 12)}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = { experiment: ExperimentNode }

interface GraphPaneProps {
  graph: Graph
  selectedId: string | null
  theme: 'dark' | 'light'
  onSelect: (id: string) => void
}

export function GraphPane({ graph, selectedId, theme, onSelect }: GraphPaneProps) {
  // dark arrowheads on a dark canvas would vanish; theme the marker only
  const arrowColor = theme === 'dark' ? '#94a3b8' : '#374151'
  const dotColor = theme === 'dark' ? '#39404e' : '#c9cdd4'
  const nodes = useMemo<ExperimentFlowNode[]>(() => {
    const positioned = layoutGraph(graph)
    return positioned.map((position) => {
      const node = graph.nodes.find((n) => n.manifest.id === position.id)
      return {
        id: position.id,
        type: 'experiment' as const,
        position: { x: position.x, y: position.y },
        data: {
          title: node?.manifest.title ?? position.id,
          expId: position.id,
          commit: node?.commit ?? '',
        },
        selected: position.id === selectedId,
      }
    })
  }, [graph, selectedId])

  const edges = useMemo<FlowEdge[]>(
    () =>
      graph.edges.map((edge) => ({
        id: `${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        // no edge labels: on short vertical drops they render inside the
        // ~20px inter-card gap and read as missing, which looks inconsistent
        // next to diagonal edges. Relationships are shown in the inspector
        // (parents/children lists) and in every manifest instead.
        type: 'smoothstep' as const,
        // tight corner radius: the default ~10px arcs graze the tile corners
        // in the ~10px inter-row channel and read as lines diving behind cards
        pathOptions: { borderRadius: 3 },
        // arrowheads only get explicit styling: with defaults they inherit
        // the faint 1px stroke color and read as "no arrowhead"; stroke and
        // routing stay untouched.
        markerEnd: { type: MarkerType.ArrowClosed, color: arrowColor, width: 18, height: 18 },
      })),
    [graph, arrowColor],
  )

  return (
    <div className="graph-pane">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode={theme}
        nodesDraggable={false}
        nodesConnectable={false}
        fitView
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={(_, node) => onSelect(node.id)}
      >
        <Background gap={24} color={dotColor} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
