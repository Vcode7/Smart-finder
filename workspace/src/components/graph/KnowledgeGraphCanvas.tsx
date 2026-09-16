// src/components/graph/KnowledgeGraphCanvas.tsx
// Interactive D3 Knowledge Graph Canvas with High-Contrast Light/Dark Mode Visibility

'use client';

import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { ZoomIn, ZoomOut, RotateCcw, ExternalLink, X, FileText } from 'lucide-react';
import { useUIStore } from '@/store/ui';
import type {
  KnowledgeGraph,
  KnowledgeGraphNode,
  KnowledgeGraphEdge,
  ResearchSession,
} from '@/types/research';

interface SimNode extends KnowledgeGraphNode {
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
  x?: number;
  y?: number;
}

interface Props {
  graph: KnowledgeGraph;
  session: ResearchSession;
}

const NODE_COLORS: Record<string, { bg: string; text: string; ring: string }> = {
  topic: { bg: '#4f46e5', text: '#6366f1', ring: 'rgba(99, 102, 241, 0.25)' },
  person: { bg: '#e11d48', text: '#f43f5e', ring: 'rgba(244, 63, 94, 0.25)' },
  organization: { bg: '#d97706', text: '#f59e0b', ring: 'rgba(245, 158, 11, 0.25)' },
  source: { bg: '#0891b2', text: '#06b6d4', ring: 'rgba(6, 182, 212, 0.25)' },
  concept: { bg: '#059669', text: '#10b981', ring: 'rgba(16, 185, 129, 0.25)' },
};

export default function KnowledgeGraphCanvas({ graph, session }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: SimNode } | null>(null);

  useEffect(() => {
    if (!svgRef.current || graph.nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width = svgRef.current.clientWidth || 800;
    const height = 480;

    const simNodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const simEdges = graph.edges.map((e) => ({ ...e }));

    const g = svg.append('g');

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      });

    zoomRef.current = zoom;
    svg.call(zoom);

    // Initial center transform
    svg.call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.95));

    // Links lines (Using dynamic theme CSS variables for high contrast)
    const link = g
      .append('g')
      .selectAll<SVGLineElement, typeof simEdges[0]>('line')
      .data(simEdges)
      .join('line')
      .attr('stroke', 'var(--text-muted)')
      .attr('stroke-width', (d) => Math.max(1.5, (d.strength || 0.5) * 2.5))
      .attr('stroke-opacity', 0.35);

    // Link labels (With halo stroke for high readability in light and dark mode)
    const linkLabel = g
      .append('g')
      .selectAll<SVGTextElement, typeof simEdges[0]>('text')
      .data(simEdges.filter((e) => e.label))
      .join('text')
      .attr('fill', 'var(--text-secondary)')
      .attr('font-size', 9)
      .attr('font-family', 'sans-serif')
      .attr('font-weight', '600')
      .attr('text-anchor', 'middle')
      .attr('paint-order', 'stroke fill')
      .attr('stroke', 'var(--bg-base)')
      .attr('stroke-width', 3)
      .attr('stroke-linejoin', 'round')
      .text((d) => d.label || '');

    // Nodes group
    const node = g
      .append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'pointer')
      .on('click', (_, d) => {
        setSelectedNode((prev) => (prev?.id === d.id ? null : d));
      })
      .on('mouseover', (event: MouseEvent, d) => {
        setTooltip({ x: event.clientX, y: event.clientY, node: d });
      })
      .on('mouseout', () => setTooltip(null));

    // Drag behavior
    const dragHandler = d3
      .drag<SVGGElement, SimNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x as number;
        d.fy = event.y as number;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    node.call(dragHandler as unknown as (sel: d3.Selection<SVGGElement, SimNode, SVGGElement, unknown>) => void);

    // Outer glow circle
    node
      .append('circle')
      .attr('r', (d) => (d.type === 'source' ? 14 : 11))
      .attr('fill', (d) => (NODE_COLORS[d.type] || NODE_COLORS.concept).ring);

    // Core circle
    node
      .append('circle')
      .attr('r', (d) => (d.type === 'source' ? 8 : 7))
      .attr('fill', (d) => (NODE_COLORS[d.type] || NODE_COLORS.concept).bg)
      .attr('stroke', 'var(--bg-card)')
      .attr('stroke-width', 2);

    // High-Contrast Node Text Label with theme-adaptive stroke halo
    node
      .append('text')
      .attr('dy', 22)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', 11)
      .attr('font-weight', '700')
      .attr('font-family', 'sans-serif')
      .attr('letter-spacing', '0.01em')
      .attr('paint-order', 'stroke fill')
      .attr('stroke', 'var(--bg-base)')
      .attr('stroke-width', 3.5)
      .attr('stroke-linejoin', 'round')
      .text((d) => (d.label.length > 22 ? d.label.slice(0, 20) + '…' : d.label));

    // Force simulation
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, typeof simEdges[0]>(simEdges)
          .id((d) => d.id)
          .distance(105)
      )
      .force('charge', d3.forceManyBody().strength(-280))
      .force('center', d3.forceCenter(0, 0))
      .force('collision', d3.forceCollide(30))
      .on('tick', () => {
        link
          .attr('x1', (d) => (d.source as unknown as SimNode).x ?? 0)
          .attr('y1', (d) => (d.source as unknown as SimNode).y ?? 0)
          .attr('x2', (d) => (d.target as unknown as SimNode).x ?? 0)
          .attr('y2', (d) => (d.target as unknown as SimNode).y ?? 0);

        linkLabel
          .attr(
            'x',
            (d) =>
              (((d.source as unknown as SimNode).x ?? 0) +
                ((d.target as unknown as SimNode).x ?? 0)) /
              2
          )
          .attr(
            'y',
            (d) =>
              (((d.source as unknown as SimNode).y ?? 0) +
                ((d.target as unknown as SimNode).y ?? 0)) /
              2
          );

        node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });

    return () => {
      simulation.stop();
    };
  }, [graph]);

  const handleZoom = (factor: number) => {
    if (!svgRef.current || !zoomRef.current) return;
    d3.select(svgRef.current)
      .transition()
      .duration(250)
      .call(zoomRef.current.scaleBy, factor);
  };

  const handleResetZoom = () => {
    if (!svgRef.current || !zoomRef.current) return;
    const width = svgRef.current.clientWidth || 800;
    const height = 480;
    d3.select(svgRef.current)
      .transition()
      .duration(350)
      .call(
        zoomRef.current.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.95)
      );
  };

  const types = Object.entries(NODE_COLORS);

  return (
    <div className="relative overflow-hidden mesh-grid rounded-2xl border" style={{ background: 'var(--bg-base)', borderColor: 'var(--border)', minHeight: 480 }}>
      {/* SVG Canvas */}
      <svg ref={svgRef} className="w-full" style={{ height: 480 }} />

      {/* Floating Zoom & Canvas Controls */}
      <div className="absolute top-4 left-4 flex items-center p-1 rounded-xl border backdrop-blur-xl shadow-lg gap-1" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <button
          onClick={() => handleZoom(1.25)}
          className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]"
          title="Zoom In"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={() => handleZoom(0.8)}
          className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]"
          title="Zoom Out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <div className="w-px h-4 bg-[var(--border)]" />
        <button
          onClick={handleResetZoom}
          className="p-1.5 rounded-lg transition-colors hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]"
          title="Reset View"
        >
          <RotateCcw className="w-4 h-4" />
        </button>
      </div>

      {/* Legend Badge Bar */}
      <div className="absolute bottom-4 left-4 flex flex-wrap gap-2 p-1.5 rounded-2xl border backdrop-blur-xl shadow-lg" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        {types.map(([type, color]) => (
          <div
            key={type}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold"
            style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}
          >
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: color.bg }} />
            <span className="capitalize">{type}</span>
          </div>
        ))}
      </div>

      {/* Tooltip on Hover */}
      {tooltip && !selectedNode && (
        <div
          className="fixed z-50 px-3 py-2 rounded-xl text-xs pointer-events-none shadow-2xl border backdrop-blur-xl"
          style={{
            left: tooltip.x + 15,
            top: tooltip.y - 10,
            background: 'var(--bg-elevated)',
            borderColor: 'var(--border)',
            color: 'var(--text-primary)',
          }}
        >
          <p className="font-bold">{tooltip.node.label}</p>
          <p className="capitalize text-[10px] font-semibold" style={{ color: (NODE_COLORS[tooltip.node.type] || NODE_COLORS.concept).text }}>
            {tooltip.node.type}
          </p>
        </div>
      )}

      {/* Selected Node Inspector Drawer */}
      {selectedNode && (
        <div
          className="absolute top-4 right-4 w-72 p-4 rounded-2xl border shadow-2xl backdrop-blur-2xl animate-in fade-in slide-in-from-right-4"
          style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
        >
          <div className="flex items-start justify-between gap-2 mb-2">
            <div>
              <span
                className="text-[10px] font-mono uppercase px-2 py-0.5 rounded-full font-bold"
                style={{
                  background: `${(NODE_COLORS[selectedNode.type] || NODE_COLORS.concept).bg}20`,
                  color: (NODE_COLORS[selectedNode.type] || NODE_COLORS.concept).text,
                }}
              >
                {selectedNode.type}
              </span>
              <h4 className="text-sm font-bold mt-1.5" style={{ color: 'var(--text-primary)' }}>
                {selectedNode.label}
              </h4>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="p-1 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {selectedNode.sourceIds && selectedNode.sourceIds.length > 0 && (
            <div className="mt-3 pt-3 border-t space-y-2" style={{ borderColor: 'var(--border)' }}>
              <p className="text-[11px] font-bold" style={{ color: 'var(--text-muted)' }}>Linked Research Sources:</p>
              <div className="max-h-36 overflow-y-auto space-y-1.5">
                {selectedNode.sourceIds.map((id) => {
                  const source = session.sources.find((s) => s.id === id);
                  if (!source) return null;
                  return (
                    <button
                      key={id}
                      onClick={() => useUIStore.getState().openSourceModal(source.id, 'details')}
                      className="w-full flex items-center justify-between gap-2 p-2 rounded-xl border text-xs text-left hover:bg-[var(--bg-hover)] transition-all group cursor-pointer"
                      style={{ background: 'var(--bg-base)', borderColor: 'var(--border)' }}
                    >
                      <span className="truncate flex-1 font-medium group-hover:text-indigo-400" style={{ color: 'var(--text-primary)' }}>
                        {source.title}
                      </span>
                      <FileText className="w-3 h-3 text-[var(--text-muted)] group-hover:text-indigo-400 flex-shrink-0" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
