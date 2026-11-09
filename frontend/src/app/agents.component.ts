import { Component, inject, signal, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Api } from './api.service';
interface Site { id: string; name: string; agents: number; }
@Component({ standalone: true, template: `
  <h2>Agents & sites</h2>
  <div class="card">
    <p class="mut">Installez l'agent UDME sur le PC de la pharmacie, puis enrôlez-le avec un jeton à usage unique (valable 30 minutes).</p>
    @for (s of sites(); track s.id) {
      <div class="row" style="margin-bottom:8px"><strong>{{s.name}}</strong><span class="badge">{{s.agents}} agent(s) actif(s)</span>
        @if (api.me()?.role === 'admin') { <button class="p" (click)="issue(s)">Générer un jeton d'enrôlement</button> }</div> }
    @if (!sites().length) { <p class="mut">Aucun site.</p> }
  </div>
  @if (token(); as t) { <div class="card warn" role="status"><p><strong>Jeton affiché une seule fois.</strong> Sur le PC de la pharmacie, exécutez :</p>
    <pre style="white-space:pre-wrap;user-select:all">udme-agent enroll --server {{origin}} --token {{t}}</pre>
    <p class="mut">Ensuite : lancez « Démarrer UDME Agent » sur le PC. L'agent vous demandera ce jeton, vous laissera choisir une base compatible, puis enverra son schéma ici. Les fichiers .sql sont des sauvegardes et ne sont pas importés automatiquement.</p></div> }
  @if (err()) { <p class="err" role="alert">{{err()}}</p> }` })
export class AgentsComponent implements OnInit {
  api = inject(Api); private http = inject(HttpClient);
  sites = signal<Site[]>([]); token = signal(''); err = signal(''); origin = location.origin;
  ngOnInit() { this.http.get<Site[]>('/api/v1/sites').subscribe(s => this.sites.set(s)); }
  issue(s: Site) { this.err.set('');
    this.http.post<{ token: string }>(`/api/v1/sites/${s.id}/enrollment-tokens`, {}).subscribe({ next: r => this.token.set(r.token), error: () => this.err.set('Action refusée.') }); }
}
