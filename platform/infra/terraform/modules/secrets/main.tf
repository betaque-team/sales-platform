terraform {
  required_providers {
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

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

# ED25519 deploy key for private repo access on the VM.
# Public key → add to GitHub repo Settings > Deploy keys (read-only).
# Private key → injected into VM via cloud-init, never stored locally.
resource "tls_private_key" "github_deploy" {
  algorithm = "ED25519"
}

locals {
  postgres_password = var.postgres_password_override != "" ? var.postgres_password_override : random_password.postgres.result
  jwt_secret        = var.jwt_secret_override != "" ? var.jwt_secret_override : random_password.jwt.result
}
