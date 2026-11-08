import { Component, ElementRef, Input, Output, EventEmitter, OnChanges, OnDestroy, ViewChild, AfterViewInit } from '@angular/core';
import cytoscape from 'cytoscape';
import { Graph, Edge } from './api.service';

const DOMAIN_COLORS: Record<string, string> = { catalog: '#2f80ed', inventory: '#27ae60', sales: '#e67e22', procurement: '#9b51e0',
  customers: '#eb5757', security: '#7f8c8d', reference: '#00a3a3' };

/** Filtered ERD: renders only edges >= minScore (and optionally hides unlinked tables) to keep large schemas usable. */
@Component({ selector: 'app-graph', standalone: true, template: `<div #host role="img"
  aria-label="Graphe des relations entre tables. Une vue tableau équivalente est disponible dans l'onglet Revue."
  style="height:520px;border:1px solid var(--bd);border-radius:8px"></div>` })
export class GraphComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('host', { static: true }) host!: ElementRef<HTMLDivElement>;
  @Input() graph: Graph | null = null; @Input() minScore = 0.6; @Input() hideUnlinked = true;
  @Output() edgeSelected = new EventEmitter<Edge>();
  private cy?: cytoscape.Core;
  ngAfterViewInit() { this.draw(); }
  ngOnChanges() { if (this.cy) this.draw(); }
  ngOnDestroy() { this.cy?.destroy(); }
  private draw() {
    this.cy?.destroy();
    if (!this.graph) return;
    const edges = this.graph.edges.filter(e => e.score >= this.minScore && e.status !== 'rejected');
    const linked = new Set(edges.flatMap(e => [e.source_table, e.target_table]));
    const nodes = this.graph.nodes.filter(n => !this.hideUnlinked || linked.has(n.id)).slice(0, 300); // hard cap
    const ids = new Set(nodes.map(n => n.id));
    const style = getComputedStyle(document.body);
    this.cy = cytoscape({
      container: this.host.nativeElement,
      elements: [
        ...nodes.map(n => ({ data: { id: n.id, label: n.id.split('.').pop() + (n.label && n.label !== 'UNKNOWN' ? `\n${n.label}` : ''),
          color: DOMAIN_COLORS[(n.label ?? '').split('.')[0]] ?? '#98a2b3' } })),
        ...edges.filter(e => ids.has(e.source_table) && ids.has(e.target_table)).map(e => ({ data: { id: e.id, source: e.source_table, target: e.target_table,
          label: `${e.score.toFixed(2)}${e.declared ? '' : '?'}`, declared: e.declared ? 1 : 0, ref: e } })),
      ],
      layout: { name: 'cose', animate: false, nodeRepulsion: () => 9000 } as any,
      style: [
        { selector: 'node', style: { 'background-color': 'data(color)', label: 'data(label)', 'font-size': 10, color: style.color, 'text-wrap': 'wrap',
          'text-valign': 'bottom', 'text-margin-y': 4, width: 22, height: 22 } },
        { selector: 'edge', style: { width: 2, 'line-color': '#98a2b3', 'target-arrow-color': '#98a2b3', 'target-arrow-shape': 'triangle',
          'curve-style': 'bezier', label: 'data(label)', 'font-size': 9, color: style.color, 'line-style': 'dashed' } },
        { selector: 'edge[declared = 1]', style: { 'line-style': 'solid', 'line-color': '#27ae60', 'target-arrow-color': '#27ae60' } },
        { selector: ':selected', style: { 'border-width': 3, 'border-color': '#1f5fbf', 'line-color': '#1f5fbf' } },
      ],
    });
    this.cy.on('tap', 'edge', ev => this.edgeSelected.emit(ev.target.data('ref') as Edge));
  }
}
