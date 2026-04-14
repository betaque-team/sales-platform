variable "cloudflare_account_id" {
  description = "Cloudflare account ID"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for the domain"
  type        = string
}

variable "tunnel_name" {
  description = "Name for the Cloudflare Tunnel"
  type        = string
  default     = "sales-platform"
}

variable "domain" {
  description = "Full domain for the app (e.g., salesplatform.reventlabs.com)"
  type        = string
}

variable "subdomain" {
  description = "Subdomain part only (e.g., salesplatform)"
  type        = string
  default     = ""
}
