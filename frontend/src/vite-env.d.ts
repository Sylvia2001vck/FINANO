/// <reference types="vite/client" />

import type {} from "axios";

declare module "axios" {
  interface AxiosRequestConfig {
    /** 为 true 时不计入全局 Loading，避免长请求卡住整页 Spin */
    skipGlobalLoading?: boolean;
  }
}
