import { useEffect, useRef, useState } from "react";

/** Minimaler fetch-Wrapper mit loading/error/data-State.
 *  Re-fetched bei Aenderung der Dependency-Liste. */
export function useApi(url, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    setLoading(true);
    setError(null);

    fetch(url)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then((json) => {
        if (!cancelled.current) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled.current) {
          setError(e.message || String(e));
          setLoading(false);
        }
      });

    return () => {
      cancelled.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}

/** Imperativer POST -- gibt eine Funktion zurueck, die das Promise liefert. */
export async function apiPost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

/** Heutiges Datum als YYYY-MM-DD im lokalen Tagesrhythmus. */
export function todayIso() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
