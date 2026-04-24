export interface User {
  id: number;
  username: string;
  email: string;
  created_at: string;
  updated_at: string;
  mbti?: string | null;
  birth_date?: string | null;
  birth_time_slot?: string | null;
  layout_facing?: string | null;
  risk_preference?: number | null;
  fbti_profile?: string | null;
  user_wuxing?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}
