import axios from "axios";
import { message } from "antd";
import { useAppStore } from "../store/appStore";
import { useUserStore } from "../store/userStore";

export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message: string;
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1"
});

api.interceptors.request.use((config) => {
  useAppStore.getState().incLoading();
  const token = useUserStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    useAppStore.getState().decLoading();
    return response;
  },
  (error) => {
    useAppStore.getState().decLoading();
    const status = error?.response?.status;
    const url = String(error?.config?.url ?? "");
    const isAuthEntry = url.includes("/auth/login") || url.includes("/auth/register");
    if (status === 401 && !isAuthEntry) {
      useUserStore.getState().logout();
      message.warning("登录已过期，请重新登录");
      window.location.assign("/login");
    }
    const msg = error?.response?.data?.message || error?.message || "请求失败";
    return Promise.reject(new Error(typeof msg === "string" ? msg : "请求失败"));
  }
);
