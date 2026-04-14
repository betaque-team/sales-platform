variable "compartment_id" {
  description = "OCI compartment OCID"
  type        = string
}

variable "subnet_id" {
  description = "Subnet OCID to place the instance in"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key content for instance access"
  type        = string
}

variable "instance_name" {
  description = "Display name for the compute instance"
  type        = string
  default     = "sales-platform"
}

variable "instance_shape" {
  description = "OCI compute shape (free tier: VM.Standard.A1.Flex)"
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  description = "Number of OCPUs (free tier max: 4)"
  type        = number
  default     = 4

  validation {
    condition     = var.ocpus >= 1 && var.ocpus <= 4
    error_message = "Free tier allows max 4 OCPUs for A1.Flex."
  }
}

variable "memory_gb" {
  description = "Memory in GB (free tier max: 24)"
  type        = number
  default     = 24

  validation {
    condition     = var.memory_gb >= 1 && var.memory_gb <= 24
    error_message = "Free tier allows max 24 GB for A1.Flex."
  }
}

variable "boot_volume_gb" {
  description = "Boot volume size in GB (free tier max: 200)"
  type        = number
  default     = 100

  validation {
    condition     = var.boot_volume_gb >= 47 && var.boot_volume_gb <= 200
    error_message = "Boot volume must be 47-200 GB (free tier max 200)."
  }
}

variable "cloud_init_data" {
  description = "Base64-encoded cloud-init user data"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Freeform tags for the instance"
  type        = map(string)
  default     = {}
}
