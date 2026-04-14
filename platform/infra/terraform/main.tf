# =============================================================================
# Sales Data Platform — Terraform Root Module
# Provisions OCI VM + Cloudflare Tunnel + DNS + Monitoring
# Usage: make infra-up
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
  }
}

# --- Providers ---
provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.api_key_fingerprint
  private_key_path = var.api_private_key_path
  region           = var.region
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# --- Locals ---
locals {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
}

# =============================================================================
# Modules
# =============================================================================

module "secrets" {
  source = "./modules/secrets"

  postgres_password_override = var.postgres_password
  jwt_secret_override        = var.jwt_secret
}

module "network" {
  source = "./modules/network"

  compartment_id        = local.compartment_id
  project_name          = var.instance_name
  allowed_ingress_ports = [22] # SSH only — tunnel handles web traffic
}

module "cloudflare" {
  source = "./modules/cloudflare"

  cloudflare_account_id = var.cloudflare_account_id
  cloudflare_zone_id    = var.cloudflare_zone_id
  tunnel_name           = var.instance_name
  domain                = var.app_domain
  subdomain             = var.app_subdomain
}

module "compute" {
  source = "./modules/compute"

  compartment_id = local.compartment_id
  subnet_id      = module.network.subnet_id
  ssh_public_key = file(var.ssh_public_key_path)
  instance_name  = var.instance_name
  ocpus          = var.instance_ocpus
  memory_gb      = var.instance_memory_gb
  boot_volume_gb = var.boot_volume_gb

  cloud_init_data = base64gzip(templatefile(
    "${path.module}/modules/compute/templates/cloud-init.yaml.tpl",
    {
      app_domain              = var.app_domain
      tunnel_token            = module.cloudflare.tunnel_token
      postgres_password       = module.secrets.postgres_password
      jwt_secret              = module.secrets.jwt_secret
      anthropic_api_key       = var.anthropic_api_key
      git_repo_url            = var.git_repo_url
      instance_name           = var.instance_name
      # Base64-encoded so it survives YAML/cloud-init escaping safely.
      # Decoded on first boot and written to /root/.ssh/id_ed25519 (600).
      github_deploy_key_b64   = base64encode(module.secrets.github_deploy_key_private)
    }
  ))
}

module "monitoring" {
  source = "./modules/monitoring"

  compartment_id = local.compartment_id
  instance_id    = module.compute.instance_id
  project_name   = var.instance_name
  alert_email    = var.alert_email
  budget_enabled = false  # Skip budget (requires IAM policy not available on free tier)
}
