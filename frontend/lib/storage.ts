/**
 * Audits are kept in the browser (localStorage): the hosted backend is
 * stateless, so there is no server database to look them up from.
 */
import type { Audit, AuditListItem } from "./api";

const INDEX = "seo-audit:index";
const KEY = (id: string) => `seo-audit:audit:${id}`;
const MAX_SAVED = 10;

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function listAudits(): AuditListItem[] {
  return read<AuditListItem[]>(INDEX, []);
}

export function getAudit(id: string): Audit | null {
  return read<Audit | null>(KEY(id), null);
}

export function saveAudit(audit: Audit): void {
  const item: AuditListItem = {
    id: audit.id,
    url: audit.url,
    created_at: audit.created_at,
    overall_score: audit.overall_score,
    grade: audit.grade,
  };
  let index = [item, ...listAudits().filter((a) => a.id !== audit.id)];
  for (const old of index.slice(MAX_SAVED)) remove(old.id);
  index = index.slice(0, MAX_SAVED);
  // On quota errors drop the oldest saved audits until it fits.
  while (index.length) {
    try {
      localStorage.setItem(KEY(audit.id), JSON.stringify(audit));
      localStorage.setItem(INDEX, JSON.stringify(index));
      return;
    } catch {
      const oldest = index.pop();
      if (!oldest || oldest.id === audit.id) return;
      remove(oldest.id);
    }
  }
}

function remove(id: string) {
  try {
    localStorage.removeItem(KEY(id));
  } catch {}
}

export function deleteAudit(id: string): void {
  remove(id);
  try {
    localStorage.setItem(INDEX, JSON.stringify(listAudits().filter((a) => a.id !== id)));
  } catch {}
}
