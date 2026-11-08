import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';

export interface ScanRow { id: string; site: string; engine: string; status: string; schema_hash: string; created_at: string; }
export interface ScanDetail { id: string; status: string; engine: string; engine_version: string; warnings: string[];
  metadata_only: boolean; objects: { schema: string; name: string; type: string; columns: number }[]; pending_reviews: number; }
export interface TableInfo { id: string; type: string; primary_key: string[];
  columns: { name: string; ordinal: number; native_type: string; normalized_type: string; nullable: boolean | null }[];
  foreign_keys: unknown[]; indexes: unknown[]; }
export interface Edge { id: string; source_table: string; source_columns: string[]; target_table: string; target_columns: string[];
  candidate_type: string; score: number; evidence: string[]; declared: boolean; status: string; }
export interface Node { id: string; mapping_id?: string; label?: string; confidence?: number; status?: string; evidence?: string[]; alternatives?: string[]; }
export interface Graph { nodes: Node[]; edges: Edge[]; }

const KEY = 'udme_token';  // sessionStorage: cleared when the tab closes
@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);
  token = signal<string | null>(sessionStorage.getItem(KEY));
  me = signal<{ user: string; tenant: string; role: string } | null>(null);
  login(username: string, password: string) {
    return this.http.post<{ token: string }>('/api/v1/auth/login', { username, password }).pipe(
      tap(r => { sessionStorage.setItem(KEY, r.token); this.token.set(r.token); this.loadMe(); }));
  }
  loadMe() { this.http.get<any>('/api/v1/auth/me').subscribe({ next: m => this.me.set(m), error: () => this.logout() }); }
  logout() { sessionStorage.removeItem(KEY); this.token.set(null); this.me.set(null); }
  scans() { return this.http.get<ScanRow[]>('/api/v1/scans'); }
  scan(id: string) { return this.http.get<ScanDetail>(`/api/v1/scans/${id}`); }
  tables(id: string) { return this.http.get<TableInfo[]>(`/api/v1/scans/${id}/tables`); }
  graph(id: string, minScore = 0) { return this.http.get<Graph>(`/api/v1/scans/${id}/graph?min_score=${minScore}`); }
  reviewRel(id: string, decision: string, comment = '') { return this.http.post(`/api/v1/relationships/${id}/review`, { decision, comment }); }
  reviewMap(id: string, decision: string, label?: string, comment = '') { return this.http.post(`/api/v1/mappings/${id}/review`, { decision, label, comment }); }
  diff(id: string, base: string) { return this.http.get<any>(`/api/v1/scans/${id}/diff/${base}`); }
  export(id: string, fmt: string) { return this.http.get(`/api/v1/scans/${id}/export?fmt=${fmt}`, { responseType: 'blob' }); }
}
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const t = inject(Api).token();
  return next(t && req.url.startsWith('/api/') ? req.clone({ setHeaders: { Authorization: `Token ${t}` } }) : req);
};
