'use client';
// src/components/graph/InteractiveKnowledgeGraphView.tsx
// Interactive Knowledge Graph Canvas with Entity Extraction, Node Details Drawer, and Source Citations

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import * as d3 from 'd3';
import { Share2, ZoomIn, ZoomOut, RotateCcw, X, ExternalLink, Info, Layers, Tag } from 'lucide-react';
import type { KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge } from '@/types/research';

interface Props {
  graph: KnowledgeGraph;
  topic?: string;
  onOpenSource?: (sourceId: string) => void;
}

interface SimNode extends KnowledgeGraphNode {
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

const ENTITY_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  person: { label: 'People', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.15)', border: '#06b6d4' },
  organization: { label: 'Organizations', color: '#6366f1', bg: 'rgba(99, 102, 241, 0.15)', border: '#6366f1' },
  event: { label: 'Events', color: '#f43f5e', bg: 'rgba(244, 63, 94, 0.15)', border: '#f43f5e' },
  location: { label: 'Locations', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)', border: '#10b981' },
  concept: { label: 'Concepts', color: '#a855f7', bg: 'rgba(168, 85, 247, 0.15)', border: '#a855f7' },
  topic: { label: 'Topics', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)', border: '#3b82f6' },
  source: { label: 'Documents', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', border: '#f59e0b' },
};

export default function InteractiveKnowledgeGraphView({ graph, topic, onOpenSource }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [activeTypeFilter, setActiveTypeFilter] = useState<string>('all');
  const zoomBehaviorRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    if (!svgRef.current || !graph.nodes || graph.nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const width = svgRef.current.clientWidth || 700;
    const height = 400;

    const simNodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const simEdges = graph.edges.map((e) => ({ ...e }));

    const g = svg.append('g');

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform.toString());
      });

    zoomBehaviorRef.current = zoom;
    svg.call(zoom);

    // Initial centering
    svg.call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.95));

    // Links
    const link = g
      .append('g')
      .selectAll('line')
      .data(simEdges)
      .join('line')
      .attr('stroke', 'var(--border)')
      .attr('stroke-width', 2)
      .attr('stroke-opacity', 0.6);

    // Link Labels
    const linkLabels = g
      .append('g')
      .selectAll('text')
      .data(simEdges.filter((e) => e.label))
      .join('text')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', 9)
      .attr('font-weight', '600')
      .attr('text-anchor', 'middle')
      .attr('paint-order', 'stroke fill')
      .attr('stroke', 'var(--bg-elevated)')
      .attr('stroke-width', 3)
      .text((d) => d.label || '');

    // Nodes
    const node = g
      .append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes)
      .join('g')
      .attr('cursor', 'pointer')
      .on('click', (event, d) => {
        event.stopPropagation();
        setSelectedNode(d);
      });

    // Node circles with glowing ring
    node
      .append('circle')
      .attr('r', (d) => (d.type === 'topic' ? 24 : 18))
      .attr('fill', (d) => ENTITY_CONFIG[d.type]?.bg || 'rgba(99, 102, 241, 0.2)')
      .attr('stroke', (d) => ENTITY_CONFIG[d.type]?.border || '#6366f1')
      .attr('stroke-width', 2.5)
      .attr('filter', 'drop-shadow(0 2px 8px rgba(0,0,0,0.3))');

    // Node Labels
    node
      .append('text')
      .attr('dy', (d) => (d.type === 'topic' ? 36 : 30))
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', 11)
      .attr('font-weight', '700')
      .attr('paint-order', 'stroke fill')
      .attr('stroke', 'var(--bg-elevated)')
      .attr('stroke-width', 3)
      .text((d) => d.label);

    // Force simulation
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, typeof simEdges[0]>(simEdges)
          .id((d) => d.id)
          .distance(110)
      )
      .force('charge', d3.forceManyBody().strength(-240))
      .force('center', d3.forceCenter(0, 0))
      .force('collision', d3.forceCollide().radius(40));

    // Drag behavior
    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    node.call(drag);

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      linkLabels
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2);

      node.attr('transform', (d) => `translate(${d.x || 0}, ${d.y || 0})`);
    });

    return () => {
      simulation.stop();
    };
  }, [graph]);

  const handleResetZoom = () => {
    if (svgRef.current && zoomBehaviorRef.current) {
      const width = svgRef.current.clientWidth || 700;
      const height = 400;
      d3.select(svgRef.current)
        .transition()
        .duration(400)
        .call(zoomBehaviorRef.current.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.95));
    }
  };

  return (
    <div
      className="p-5 rounded-3xl space-y-4 shadow-xl relative overflow-hidden"
      style={{
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        boxShadow: '0 12px 36px rgba(0,0,0,0.25)',
      }}
    >
      {/* Header & Legend */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center"
            style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#6366f1' }}>
            <Share2 className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              Interactive Entity & Concept Knowledge Graph
            </h3>
            <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {graph.nodes.length} entities & {graph.edges.length} cross-source relationships mapped
            </p>
          </div>
        </div>

        {/* Zoom Controls */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleResetZoom}
            className="p-1.5 rounded-lg bg-[var(--bg-base)] border border-[var(--border)] text-zinc-400 hover:text-zinc-200 transition-colors"
            title="Reset Canvas View"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Entity Legend Badges */}
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        {Object.entries(ENTITY_CONFIG).map(([type, cfg]) => (
          <span
            key={type}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-full font-semibold"
            style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}
          >
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.color }} />
            <span>{cfg.label}</span>
          </span>
        ))}
      </div>

      {/* Interactive SVG Canvas */}
      <div className="relative w-full h-[380px] rounded-2xl overflow-hidden bg-[var(--bg-base)] border border-[var(--border)]">
        <svg ref={svgRef} className="w-full h-full" />

        {/* Selected Node Details Drawer */}
        <AnimatePresence>
          {selectedNode && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="absolute right-3 top-3 bottom-3 w-64 p-4 rounded-2xl shadow-2xl backdrop-blur-xl space-y-3 z-10 overflow-y-auto"
              style={{
                background: 'rgba(15, 23, 42, 0.94)',
                border: '1px solid rgba(99, 102, 241, 0.3)',
              }}
            >
              <div className="flex items-center justify-between">
                <span
                  className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                  style={{
                    background: ENTITY_CONFIG[selectedNode.type]?.bg || 'rgba(99, 102, 241, 0.2)',
                    color: ENTITY_CONFIG[selectedNode.type]?.color || '#6366f1',
                  }}
                >
                  {ENTITY_CONFIG[selectedNode.type]?.label || selectedNode.type}
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedNode(null)}
                  className="p-1 rounded-md text-zinc-400 hover:text-white"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div>
                <h4 className="text-sm font-bold text-white">{selectedNode.label}</h4>
                <p className="text-[11px] text-zinc-400 mt-1">
                  Entity extracted from research context and linked across documents.
                </p>
              </div>

              {selectedNode.sourceIds && selectedNode.sourceIds.length > 0 && (
                <div className="space-y-1.5 pt-2 border-t border-white/10">
                  <span className="text-[10px] font-bold text-zinc-400 uppercase">Supporting Sources:</span>
                  <div className="flex flex-col gap-1">
                    {selectedNode.sourceIds.map((sid, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => onOpenSource?.(sid)}
                        className="flex items-center justify-between text-left text-xs text-indigo-300 hover:text-indigo-200 px-2.5 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 transition-colors"
                      >
                        <span className="truncate">View Source Reference</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0 ml-1" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
