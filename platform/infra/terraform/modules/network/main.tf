terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
}

resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "${var.project_name}-vcn"
  dns_label      = replace(var.project_name, "-", "")

  freeform_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-igw"
  enabled        = true
}

resource "oci_core_route_table" "main" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-rt"

  route_rules {
    network_entity_id = oci_core_internet_gateway.main.id
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
  }
}

resource "oci_core_security_list" "main" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.project_name}-sl"

  # Egress: allow all outbound (needed for Docker pulls, tunnel, apt)
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
    stateless   = false
  }

  # Ingress: configurable TCP ports (default: SSH only)
  dynamic "ingress_security_rules" {
    for_each = var.allowed_ingress_ports
    content {
      protocol  = "6" # TCP
      source    = "0.0.0.0/0"
      stateless = false
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  # ICMP: path MTU discovery
  ingress_security_rules {
    protocol  = "1" # ICMP
    source    = "0.0.0.0/0"
    stateless = false
    icmp_options {
      type = 3
      code = 4
    }
  }

  # ICMP: ping within VCN
  ingress_security_rules {
    protocol  = "1"
    source    = var.vcn_cidr
    stateless = false
    icmp_options {
      type = 8
    }
  }
}

resource "oci_core_subnet" "main" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.main.id
  cidr_block                 = var.subnet_cidr
  display_name               = "${var.project_name}-subnet"
  dns_label                  = "pub"
  route_table_id             = oci_core_route_table.main.id
  security_list_ids          = [oci_core_security_list.main.id]
  prohibit_public_ip_on_vnic = false

  freeform_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}
