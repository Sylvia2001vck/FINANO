import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AppLocale } from "../i18n/types";

interface LocaleState {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: "zh-HK",
      setLocale: (locale) => set({ locale })
    }),
    { name: "finano-locale" }
  )
);
