import { create } from "zustand";

interface FbtiState {
  lastCode: string | null;
  lastWuxing: string | null;
  setLast: (code: string | null, wuxing: string | null) => void;
}

export const useFbtiStore = create<FbtiState>((set) => ({
  lastCode: null,
  lastWuxing: null,
  setLast: (code, wuxing) => set({ lastCode: code, lastWuxing: wuxing })
}));
