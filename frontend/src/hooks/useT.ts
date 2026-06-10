import { useMemo } from "react";
import { translate } from "../i18n";
import { useLocaleStore } from "../store/localeStore";

export function useT() {
  const locale = useLocaleStore((s) => s.locale);
  return useMemo(
    () => ({
      locale,
      t: (key: string, params?: Record<string, string | number>) => translate(locale, key, params)
    }),
    [locale]
  );
}
