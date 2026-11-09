import { Component, inject, signal, OnDestroy, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { Api, ScanRow } from './api.service';
@Component({ standalone: true, imports: [RouterLink, DatePipe], template: `
  <h2>Scans</h2>
  <div class="card">
    <div class="row"><button (click)="refresh()">Actualiser</button>
      @if (polling()) { <span class="mut">Actualisation automatique pendant l'analyse…</span> }</div>
    @if (error()) { <p class="err" role="alert">{{error()}}</p> }
    @if (loading()) { <p class="mut">Chargement…</p> }
    @else if (!rows().length) { <p>Aucun scan. Installez l'agent, ouvrez « Démarrer UDME Agent » sur le PC, puis choisissez une base compatible. Le schéma sera envoyé après confirmation.</p> }
    @else { <table><thead><tr><th>Date</th><th>Site</th><th>Moteur</th><th>État</th><th>Empreinte du schéma</th><th></th></tr></thead><tbody>
      @for (s of rows(); track s.id) { <tr><td>{{s.created_at | date:'short'}}</td><td>{{s.site}}</td><td>{{s.engine}}</td>
        <td><span class="badge">{{statusLabel(s.status)}}</span></td><td class="mut">{{s.schema_hash.slice(0,12)}}</td>
        <td><a [routerLink]="['/scans', s.id]">Ouvrir</a></td></tr> }
    </tbody></table> }
  </div>` })
export class ScansComponent implements OnInit, OnDestroy {
  private api = inject(Api);
  private pollId?: ReturnType<typeof setInterval>;
  rows = signal<ScanRow[]>([]); loading = signal(true); polling = signal(false); error = signal('');

  ngOnInit() { this.refresh(); }

  ngOnDestroy() { this.stopPolling(); }

  refresh() {
    this.error.set('');
    this.api.scans().subscribe({
      next: rows => {
        this.rows.set(rows);
        this.loading.set(false);
        if (rows.some(scan => scan.status === 'analyzing')) this.startPolling();
        else this.stopPolling();
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Impossible de charger les scans. Vérifiez la connexion puis réessayez.');
      }
    });
  }

  statusLabel(status: string) {
    return status === 'analyzing' ? 'Analyse en cours…' :
      status === 'review_required' ? 'Mapping prêt' :
      status === 'failed' ? 'Échec de l’analyse' : status;
  }

  private startPolling() {
    if (this.pollId) return;
    this.polling.set(true);
    this.pollId = setInterval(() => this.refresh(), 2500);
  }

  private stopPolling() {
    if (this.pollId) clearInterval(this.pollId);
    this.pollId = undefined;
    this.polling.set(false);
  }
}
