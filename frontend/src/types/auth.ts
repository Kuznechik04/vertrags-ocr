export type UserRole = "user" | "admin";

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: CurrentUser;
}
