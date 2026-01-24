import { useEffect, useState } from "react";
import { apiFetch } from "./apiClient";

export type Identity = {
  role: "admin" | "team";
  auth_kind: "admin_token" | "team_token" | "oidc";
  org_id?: string | null;
  team_node_id?: string | null;
  can_write: boolean;
  permissions: string[];
};

export function useIdentity() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
      // Prefer canonical identity endpoint (backed by config service).
      // Enterprise default: rely on session cookie, not localStorage tokens.
      const whoRes = await apiFetch("/api/identity", { cache: "no-store", signal: controller.signal });
      clearTimeout(timeoutId);
      if (whoRes.ok) {
        const json = (await whoRes.json()) as Identity;
        setIdentity(json);
        setLoading(false);
        return;
      }
      if (whoRes.status === 401 || whoRes.status === 403) {
        // Not signed in / invalid session
        setIdentity(null);
        setError(null);
        setLoading(false);
        return;
      }
      setIdentity(null);
      setError(`Unable to determine identity (identity endpoint: ${whoRes.status}).`);
    } catch (e: any) {
      clearTimeout(timeoutId);
      setIdentity(null);
      if (e?.name === 'AbortError') {
        setError('Request timed out. Please check your network connection.');
      } else {
        setError(e?.message || String(e));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { identity, error, loading, refresh };
}


