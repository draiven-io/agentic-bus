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

  const refetch = useCallback(() => {
    setLoading(true);
    setError(null);
    fetcher()
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    isMounted.current = true;
    refetch();
    return () => {
      isMounted.current = false;
    };
  }, [refetch]);

  return { data, loading, error, refetch } as const;
}
