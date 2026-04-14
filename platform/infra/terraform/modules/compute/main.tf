terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 5.0"
    }
  }
}

# --- Find latest Ubuntu 22.04 aarch64 image ---
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_id
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04 Minimal aarch64"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
  state                    = "AVAILABLE"
}

# --- Get availability domains ---
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}

# --- Compute instance ---
resource "oci_core_instance" "main" {
  compartment_id      = var.compartment_id
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = var.instance_name
  shape               = var.instance_shape

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gb
  }

  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = true
    display_name     = "${var.instance_name}-vnic"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = var.cloud_init_data != "" ? var.cloud_init_data : null
  }

  freeform_tags = merge(
    {
      Project   = var.instance_name
      ManagedBy = "terraform"
    },
    var.tags
  )

  # Prevent accidental destruction
  lifecycle {
    prevent_destroy = false
  }
}
