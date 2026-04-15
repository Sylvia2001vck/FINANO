import { create } from "zustand";
import { AuthResponse, User } from "../types/user";

interface UserState {
  token: string | null;
  currentUser: User | null;
  setAuth: (payload: AuthResponse) => void;
  logout: () => void;
}

const TOKEN_KEY = "finano_token";
const USER_KEY = "finano_user";

const initialToken = localStorage.getItem(TOKEN_KEY);
const initialUser = localStorage.getItem(USER_KEY);

export const useUserStore = create<UserState>((set) => ({
  token: initialToken,
  currentUser: initialUser ? JSON.parse(initialUser) : null,
  setAuth: (payload) => {
    localStorage.setItem(TOKEN_KEY, payload.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    set({ token: payload.access_token, currentUser: payload.user });
  },
  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ token: null, currentUser: null });
  }
}));
