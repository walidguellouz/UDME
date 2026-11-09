import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';
import { Api, ScanRow } from './api.service';
@Component({ standalone: true, imports: [RouterLink, DatePipe], template: `
  <h2>Scans</h2>
  <div class="card">
    @if (loading()) { <p class="mut">Chargement…</p> }
    @else if (!rows().length) { <p>Aucun scan. Installez l'agent, ouvrez « Démarrer UDME Agent » sur le PC, puis choisissez une base compatible. Le schéma sera envoyé après confirmation.</p> }
    @else { <table><thead><tr><th>Date</th><th>Site</th><th>Moteur</th><th>État</th><th>Empreinte du schéma</th><th></th></tr></thead><tbody>
      @for (s of rows(); track s.id) { <tr><td>{{s.created_at | date:'short'}}</td><td>{{s.site}}</td><td>{{s.engine}}</td>
        <td><span class="badge">{{s.status}}</span></td><td class="mut">{{s.schema_hash.slice(0,12)}}</td>
        <td><a [routerLink]="['/scans', s.id]">Ouvrir</a></td></tr> }
    </tbody></table> }
  </div>` })
export class ScansComponent implements OnInit {
  private api = inject(Api); rows = signal<ScanRow[]>([]); loading = signal(true);
  ngOnInit() { this.api.scans().subscribe(r => { this.rows.set(r); this.loading.set(false); }); }
}
