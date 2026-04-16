import axios from "axios";
import type { InternalAxiosRequestConfig } from "axios";
import { message } from "antd";
import { useAppStore } from "../store/appStore";
import { useUserStore } from "../store/userStore";

function skipGlobalLoading(config: InternalAxiosRequestConfig): boolean {
  return Boolean(config.skipGlobalLoading);
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message: string;
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1"
});

api.interceptors.request.use((config) => {
  if (!skipGlobalLoading(config)) {
    useAppStore.getState().incLoading();
  }
  const token = useUserStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => {
    if (!skipGlobalLoading(response.config)) {
      useAppStore.getState().decLoading();
    }
    return response;
  },
  (error) => {
    const cfg = error?.config as InternalAxiosRequestConfig | undefined;
    if (!cfg || !skipGlobalLoading(cfg)) {
      useAppStore.getState().decLoading();
    }
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
