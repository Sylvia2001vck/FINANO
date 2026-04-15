import { api, ApiEnvelope } from "./api";
import { AuthResponse, User } from "../types/user";

export async function login(email: string, password: string) {
  const response = await api.post<ApiEnvelope<AuthResponse>>("/auth/login", { email, password });
  return response.data.data;
}

export async function register(username: string, email: string, password: string) {
  const response = await api.post<ApiEnvelope<AuthResponse>>("/auth/register", {
    username,
    email,
    password
  });
  return response.data.data;
}

export async function fetchMe() {
  const response = await api.get<ApiEnvelope<User>>("/users/me");
  return response.data.data;
}
