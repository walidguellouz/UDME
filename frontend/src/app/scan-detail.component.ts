import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api, ScanDetail, TableInfo, Graph, Edge, Node } from './api.service';
import { GraphComponent } from './graph.component';

type Tab = 'overview' | 'schema' | 'graph' | 'review' | 'diff' | 'export';
@Component({ standalone: true, imports: [FormsModule, GraphComponent, JsonPipe], template: `
  @if (d(); as d) {
  <h2>Scan {{d.engine}} {{d.engine_version}} <span class="badge">{{d.status}}</span></h2>
  @if (d.warnings.length) { <div class="card warn" role="alert"><strong>Couverture incomplète ou avertissements</strong>
     <ul>@for (w of d.warnings; track w) { <li>{{w}}</li> }</ul></div> }
  <nav class="tabs" aria-label="Sections">
    @for (t of tabs; track t[0]) { <button [class.on]="tab()===t[0]" (click)="tab.set(t[0])">{{t[1]}}</button> }
  </nav>

  @switch (tab()) {
  @case ('overview') {
    @if (d.conflicts) { <div class="card warn" role="alert"><strong>{{d.conflicts}} relation(s) acceptée(s) absente(s) de ce scan.</strong>
      Elles n'ont pas été supprimées : vérifiez-les dans l'onglet Revue (état « conflict »).</div> }
    <div class="card"><div class="row">
      <span>Objets : <strong>{{d.objects.length}}</strong></span>
      <span>Mode : <span class="badge">{{d.metadata_only ? 'métadonnées uniquement' : 'AVEC DONNÉES'}}</span></span>
      <span>Revues en attente : <strong>{{d.pending_reviews}}</strong></span></div>
      <p class="mut">Les étiquettes métier et relations inférées sont des <em>hypothèses</em> à valider ; aucune n'est approuvée automatiquement (sauf clés étrangères déclarées).</p></div> }

  @case ('schema') {
    <div class="card"><div class="row"><input placeholder="Filtrer tables/colonnes…" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="Filtre"></div>
      @for (t of filteredTables(); track t.id) {
        <details><summary><strong>{{t.id}}</strong> <span class="mut">{{t.type}} · {{t.columns.length}} col.</span></summary>
          <table><thead><tr><th>#</th><th>Colonne</th><th>Type natif</th><th>Normalisé</th><th>Null</th><th>PK</th></tr></thead><tbody>
          @for (c of t.columns; track c.name) { <tr><td>{{c.ordinal}}</td><td>{{c.name}}</td><td>{{c.native_type}}</td><td>{{c.normalized_type}}</td>
            <td>{{c.nullable === null ? '?' : c.nullable}}</td><td>{{t.primary_key.includes(c.name) ? '✔' : ''}}</td></tr> }
          </tbody></table></details> } </div> }

  @case ('graph') {
    <div class="card"><div class="row">
      <label>Score min. <input type="range" min="0.3" max="1" step="0.05" [ngModel]="minScore()" (ngModelChange)="minScore.set(+$event)"> {{minScore()}}</label>
      <label><input type="checkbox" [ngModel]="hideUnlinked()" (ngModelChange)="hideUnlinked.set($event)"> Masquer les tables sans lien</label>
      <span class="mut">Trait plein = FK déclarée · pointillé = inférée (« ? »)</span></div>
      <app-graph [graph]="g()" [minScore]="minScore()" [hideUnlinked]="hideUnlinked()" (edgeSelected)="sel.set($event)" />
      @if (sel(); as e) { <div class="card"><strong>{{e.source_table}}.{{e.source_columns.join(',')}} → {{e.target_table}}.{{e.target_columns.join(',')}}</strong>
        <span class="badge" [class]="cls(e.score)">{{e.score}}</span> <span class="badge">{{e.candidate_type}}</span> <span class="badge">{{e.status}}</span>
        <p class="mut">Preuves : {{e.evidence.join(' · ')}}</p>
        @if (canReview() && !e.declared) { <button (click)="rel(e,'accept')">Accepter</button> <button (click)="rel(e,'reject')">Rejeter</button>
          <button (click)="rel(e,'investigate')">À investiguer</button> } </div> } </div> }

  @case ('review') {
    <div class="card"><h3>Classifications métier</h3>
      <table><thead><tr><th>Objet</th><th>Proposition</th><th>Confiance</th><th>Preuves</th><th>État</th><th></th></tr></thead><tbody>
      @for (n of g()?.nodes ?? []; track n.id) { @if (n.mapping_id) {
        <tr><td>{{n.id}}</td><td>{{n.label}}@if (n.alternatives?.length) { <div class="mut">alt. : {{n.alternatives!.join(', ')}}</div> }</td>
          <td><span class="badge" [class]="cls(n.confidence ?? 0)">{{n.confidence}}</span></td><td class="mut">{{(n.evidence ?? []).join(' · ') || '—'}}</td>
          <td>{{n.status}}</td>
          <td>@if (canReview()) { <button (click)="map(n,'accept')">Approuver</button> <button (click)="map(n,'reject')">Rejeter</button>
            <button (click)="editLabel(n)">Modifier</button> }</td></tr> } }
      </tbody></table></div>
    <div class="card"><h3>Relations (vue tableau accessible)</h3>
      <table><thead><tr><th>Source</th><th>Cible</th><th>Type</th><th>Score</th><th>Preuves</th><th>État</th><th></th></tr></thead><tbody>
      @for (e of g()?.edges ?? []; track e.id) {
        <tr><td>{{e.source_table}}.{{e.source_columns.join(',')}}</td><td>{{e.target_table}}.{{e.target_columns.join(',')}}</td><td>{{e.candidate_type}}</td>
          <td><span class="badge" [class]="cls(e.score)">{{e.score}}</span></td><td class="mut">{{e.evidence.join(' · ')}}</td><td [class.err]="e.status === 'conflict'">{{e.status}}</td>
          <td>@if (canReview() && !e.declared) { <button (click)="rel(e,'accept')">✔</button> <button (click)="rel(e,'reject')">✘</button> }</td></tr> }
      </tbody></table></div> }

  @case ('diff') {
    <div class="card"><div class="row"><label>Comparer à : <select [(ngModel)]="baseId"><option value="">— choisir un scan —</option>
      @for (s of others(); track s.id) { <option [value]="s.id">{{s.created_at}} · {{s.engine}}</option> }</select></label>
      <button (click)="runDiff()" [disabled]="!baseId">Comparer</button></div>
      @if (diff(); as df) { <p>Tables ajoutées : <strong>{{df.tables_added.length}}</strong> · supprimées : <strong>{{df.tables_removed.length}}</strong></p>
        <pre>{{df | json}}</pre> } </div> }

  @case ('export') {
    <div class="card"><p>Les exports contiennent des noms d'objets métier (et le DDL peut révéler la logique). Les relations <em>rejetées</em> sont exclues.</p>
      <label><input type="checkbox" [(ngModel)]="confirmExport"> Je confirme avoir le droit de télécharger ces artefacts.</label>
      <p class="row">@for (f of fmts; track f[0]) { <button class="p" [disabled]="!confirmExport" (click)="download(f[0])">{{f[1]}}</button> }</p></div> }
  }
  } @else { <p class="mut">Chargement…</p> }
  @if (msg()) { <p role="status" class="mut">{{msg()}}</p> }` })
export class ScanDetailComponent implements OnInit {
  private api = inject(Api); private route = inject(ActivatedRoute);
  id = ''; d = signal<ScanDetail | null>(null); tables = signal<TableInfo[]>([]); g = signal<Graph | null>(null);
  tab = signal<Tab>('overview'); q = signal(''); minScore = signal(0.6); hideUnlinked = signal(true); sel = signal<Edge | null>(null);
  msg = signal(''); confirmExport = false; baseId = ''; diff = signal<any>(null); others = signal<any[]>([]);
  tabs: [Tab, string][] = [['overview', 'Aperçu'], ['schema', 'Schéma'], ['graph', 'Graphe'], ['review', 'Revue'], ['diff', 'Comparaison'], ['export', 'Export']];
  fmts = [['json', 'JSON'], ['csv', 'CSV relations'], ['md', 'Markdown + ERD'], ['ddl', 'SQL DDL (référence)']];
  canReview = computed(() => ['admin', 'reviewer'].includes(this.api.me()?.role ?? ''));
  filteredTables = computed(() => { const q = this.q().toLowerCase();
    return this.tables().filter(t => !q || t.id.toLowerCase().includes(q) || t.columns.some(c => c.name.toLowerCase().includes(q))); });
  ngOnInit() {
    this.id = this.route.snapshot.paramMap.get('id')!;
    this.api.scan(this.id).subscribe(x => this.d.set(x));
    this.api.tables(this.id).subscribe(x => this.tables.set(x));
    this.reload();
    this.api.scans().subscribe(s => this.others.set(s.filter(x => x.id !== this.id)));
  }
  reload() { this.api.graph(this.id).subscribe(x => this.g.set(x)); this.api.scan(this.id).subscribe(x => this.d.set(x)); }
  cls(s: number) { return 'badge ' + (s >= 0.8 ? 'b-hi' : s >= 0.6 ? 'b-md' : 'b-lo'); }
  private done(m: string) { return { next: () => { this.msg.set(m); this.sel.set(null); this.reload(); }, error: () => this.msg.set('Action refusée (droits ou erreur).') }; }
  rel(e: Edge, dec: string) { this.api.reviewRel(e.id, dec).subscribe(this.done('Relation mise à jour.')); }
  map(n: Node, dec: string) { this.api.reviewMap(n.mapping_id!, dec).subscribe(this.done('Classification mise à jour.')); }
  editLabel(n: Node) { const l = prompt('Nouvelle étiquette (ex. sales.sale)', n.label ?? ''); if (l) this.api.reviewMap(n.mapping_id!, 'edit', l).subscribe(this.done('Étiquette modifiée.')); }
  runDiff() { this.api.diff(this.id, this.baseId).subscribe(x => this.diff.set(x)); }
  download(fmt: string) {
    this.api.export(this.id, fmt).subscribe(b => { const a = document.createElement('a'); a.href = URL.createObjectURL(b);
      a.download = `udme-${this.id.slice(0, 8)}.${fmt}`; a.click(); URL.revokeObjectURL(a.href); });
  }
}
