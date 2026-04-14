# =============================================================================
# Root variables — OCI + Cloudflare + Application config
# =============================================================================

# --- OCI Authentication ---
variable "tenancy_ocid" {
  description = "OCI tenancy OCID"
  type        = string
}

variable "user_ocid" {
  description = "OCI user OCID"
  type        = string
}

variable "api_key_fingerprint" {
  description = "Fingerprint of the OCI API signing key"
  type        = string
}

variable "api_private_key_path" {
  description = "Path to OCI API private key PEM file"
  type        = string
  default     = "~/.oci/oci_api_key.pem"
}

variable "region" {
  description = "OCI region (free tier: us-ashburn-1, us-phoenix-1)"
  type        = string
  default     = "us-ashburn-1"
}

variable "compartment_ocid" {
  description = "OCI compartment OCID (leave empty to use tenancy root)"
  type        = string
  default     = ""
}

# --- Cloudflare Authentication ---
variable "cloudflare_api_token" {
  description = "Cloudflare API token with Tunnel + DNS permissions"
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for the domain"
  type        = string
}

# --- SSH ---
variable "ssh_public_key_path" {
  description = "Path to SSH public key for VM access"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_private_key_path" {
  description = "Path to SSH private key (for infra-ssh command)"
  type        = string
  default     = "~/.ssh/id_rsa"
}

# --- Compute ---
variable "instance_name" {
  description = "Name for the compute instance"
  type        = string
  default     = "sales-platform"
}

variable "instance_ocpus" {
  description = "Number of OCPUs (free tier max: 4)"
  type        = number
  default     = 4
}

variable "instance_memory_gb" {
  description = "Memory in GB (free tier max: 24)"
  type        = number
  default     = 24
}

variable "boot_volume_gb" {
  description = "Boot volume in GB (free tier max: 200)"
  type        = number
  default     = 100
}

# --- Application ---
variable "app_domain" {
  description = "Full domain for the app"
  type        = string
  default     = "salesplatform.reventlabs.com"
}

variable "app_subdomain" {
  description = "Subdomain part (e.g., salesplatform)"
  type        = string
  default     = "salesplatform"
}

variable "git_repo_url" {
  description = "Git repository URL to clone on the VM"
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Email for monitoring and budget alerts"
  type        = string
  default     = ""
}

# --- Secrets (leave empty to auto-generate) ---
variable "postgres_password" {
  description = "Postgres password (auto-generated if empty)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "jwt_secret" {
  description = "JWT signing secret (auto-generated if empty)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for AI features (optional)"
  type        = string
  default     = ""
  sensitive   = true
}
