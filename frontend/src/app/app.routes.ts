import { Routes, CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { Api } from './api.service';
import { LoginComponent } from './login.component';
import { ScansComponent } from './scans.component';
import { ScanDetailComponent } from './scan-detail.component';
import { AgentsComponent } from './agents.component';
const guard: CanActivateFn = () => inject(Api).token() ? true : inject(Router).parseUrl('/login');
export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  { path: 'scans', component: ScansComponent, canActivate: [guard] },
  { path: 'scans/:id', component: ScanDetailComponent, canActivate: [guard] },
  { path: 'agents', component: AgentsComponent, canActivate: [guard] },
  { path: '', pathMatch: 'full', redirectTo: 'scans' },
  { path: '**', redirectTo: 'scans' },
];
