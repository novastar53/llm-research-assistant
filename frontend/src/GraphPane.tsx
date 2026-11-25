import { Background, Controls, Handle, MarkerType, Position, ReactFlow } from '@xyflow/react'
import type { Edge as FlowEdge, Node, NodeProps } from '@xyflow/react'
import { useMemo } from 'react'

import { layoutGraph } from './layout'
import type { Graph } from './types'

export type ExperimentFlowNode = Node<{ title: string; expId: string }, 'experiment'>

function ExperimentNode({ data, selected }: NodeProps<ExperimentFlowNode>) {
  return (
    <div className={`exp-node${selected ? ' exp-node--selected' : ''}`}>
      <Handle type="target" position={Position.Top} />
      <div className="exp-node__title">{data.title}</div>
      <div className="exp-node__id">{data.expId}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

const nodeTypes = { experiment: ExperimentNode }

interface GraphPaneProps {
  graph: Graph
  selectedId: string | null
  onSelect: (id: string) => void
}

export function GraphPane({ graph, selectedId, onSelect }: GraphPaneProps) {
  const nodes = useMemo<ExperimentFlowNode[]>(() => {
    const positioned = layoutGraph(graph)
    return positioned.map((position) => {
      const node = graph.nodes.find((n) => n.manifest.id === position.id)
      return {
        id: position.id,
        type: 'experiment' as const,
        position: { x: position.x, y: position.y },
        data: { title: node?.manifest.title ?? position.id, expId: position.id },
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
        label: edge.relationship,
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [graph],
  )

  return (
    <div className="graph-pane">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        fitView
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={(_, node) => onSelect(node.id)}
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
