import { Component, inject, OnInit } from '@angular/core';
import { RouterLink, RouterOutlet, Router } from '@angular/router';
import { Api } from './api.service';
@Component({ selector: 'app-root', standalone: true, imports: [RouterOutlet, RouterLink], template: `
  <header><strong><a routerLink="/scans">UDME</a></strong>@if (api.token()) { <a routerLink="/scans">Scans</a><a routerLink="/agents">Agents</a> }<span class="mut">Universal Database Mapping Engine</span><span class="sp"></span>
    @if (api.me(); as m) { <span>{{m.user}} · {{m.tenant}} · <span class="badge">{{m.role}}</span></span> }
    @if (api.token()) { <button (click)="out()">Déconnexion</button> }</header>
  <main><router-outlet /></main>` })
export class AppComponent implements OnInit {
  api = inject(Api); private r = inject(Router);
  ngOnInit() { if (this.api.token()) this.api.loadMe(); }
  out() { this.api.logout(); this.r.navigate(['/login']); }
}
