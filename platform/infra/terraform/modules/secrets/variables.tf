variable "postgres_password_override" {
  description = "Manually set Postgres password. Leave empty to auto-generate."
  type        = string
  default     = ""
  sensitive   = true
}

variable "jwt_secret_override" {
  description = "Manually set JWT secret. Leave empty to auto-generate."
  type        = string
  default     = ""
  sensitive   = true
}
