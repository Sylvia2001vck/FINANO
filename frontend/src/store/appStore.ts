import { create } from "zustand";

interface AppState {
  loadingCount: number;
  incLoading: () => void;
  decLoading: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  loadingCount: 0,
  incLoading: () => set((s) => ({ loadingCount: s.loadingCount + 1 })),
  decLoading: () => set((s) => ({ loadingCount: Math.max(0, s.loadingCount - 1) }))
}));
