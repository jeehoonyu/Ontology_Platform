import { useEffect, useState } from "react";

export function useAsyncState<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loader()
      .then((result) => {
        if (!cancelled) {
          setValue(result);
          setError("");
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, deps);

  return { value, error, loading, reload: async () => setValue(await loader()) };
}
