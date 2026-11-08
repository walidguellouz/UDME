import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from './api.service';
@Component({ standalone: true, imports: [FormsModule], template: `
  <div class="card" style="max-width:380px;margin:60px auto">
    <h2>Connexion</h2>
    <p class="row"><label for="u">Utilisateur</label><input id="u" [(ngModel)]="u" name="u" autocomplete="username"></p>
    <p class="row"><label for="p">Mot de passe</label><input id="p" type="password" [(ngModel)]="p" name="p" autocomplete="current-password" (keyup.enter)="go()"></p>
    @if (err()) { <p class="err" role="alert">{{err()}}</p> }
    <button class="p" (click)="go()" [disabled]="busy()">Se connecter</button>
  </div>` })
export class LoginComponent {
  private api = inject(Api); private r = inject(Router);
  u = ''; p = ''; err = signal(''); busy = signal(false);
  go() { this.busy.set(true); this.err.set('');
    this.api.login(this.u, this.p).subscribe({ next: () => this.r.navigate(['/scans']),
      error: () => { this.err.set('Identifiants invalides.'); this.busy.set(false); } }); }
}
