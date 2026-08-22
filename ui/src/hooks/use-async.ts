"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Lightweight data-fetching hook with loading / error state.
 *
 * @param fetcher  Async function that returns data of type `T`.
 * @param deps     Dependency array – the fetcher re-runs when these change.
 */
export function useAsync<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMounted = useRef(true);

  // The latest fetcher is held in a ref so `refetch` can stay stable. Passing
  // the caller's `deps` straight to useCallback is not something the linter
  // can verify (it is a runtime value, not a literal), and a `refetch` whose
  // identity changed every render would retrigger the effect below endlessly.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refetch = useCallback(() => {
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((result) => {
        if (isMounted.current) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted.current) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
  }, []);

  useEffect(() => {
    isMounted.current = true;
    // Fetching on mount necessarily sets loading state from an effect. The
    // rule's suggested alternatives — deriving during render, or subscribing
    // to an external store — do not apply to a one-shot request; avoiding it
    // entirely would mean adopting a data-fetching library.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refetch();
    return () => {
      isMounted.current = false;
    };
    // The caller's deps decide when to refetch; `refetch` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refetch } as const;
}
