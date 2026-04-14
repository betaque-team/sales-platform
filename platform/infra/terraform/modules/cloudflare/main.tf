terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }
}

# --- Tunnel secret ---
resource "random_id" "tunnel_secret" {
  byte_length = 32
}

# --- Cloudflare Tunnel ---
resource "cloudflare_zero_trust_tunnel_cloudflared" "app" {
  account_id = var.cloudflare_account_id
  name       = var.tunnel_name
  secret     = random_id.tunnel_secret.b64_std
}

# --- Tunnel ingress configuration ---
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "app" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.app.id

  config {
    # API routes -> nginx (which proxies to backend:8000)
    ingress_rule {
      hostname = var.domain
      path     = "/api/*"
      service  = "http://localhost:8080"
      origin_request {
        connect_timeout = "30s"
        no_tls_verify   = true
      }
    }

    # Health check
    ingress_rule {
      hostname = var.domain
      path     = "/health"
      service  = "http://localhost:8080"
    }

    # All other traffic -> nginx (which proxies to frontend:80)
    ingress_rule {
      hostname = var.domain
      service  = "http://localhost:8080"
      origin_request {
        connect_timeout = "10s"
        no_tls_verify   = true
      }
    }

    # Catch-all (required)
    ingress_rule {
      service = "http_status:404"
    }
  }
}

# --- DNS CNAME record pointing to the tunnel ---
resource "cloudflare_record" "tunnel_cname" {
  zone_id = var.cloudflare_zone_id
  name    = var.subdomain != "" ? var.subdomain : var.domain
  content = "${cloudflare_zero_trust_tunnel_cloudflared.app.id}.cfargotunnel.com"
  type    = "CNAME"
  proxied = true
  ttl     = 1 # Auto when proxied
  comment = "Managed by Terraform - ${var.tunnel_name} tunnel"
}
