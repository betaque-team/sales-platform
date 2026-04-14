output "public_ip" {
  description = "Public IP address of the instance"
  value       = oci_core_instance.main.public_ip
}

output "private_ip" {
  description = "Private IP address of the instance"
  value       = oci_core_instance.main.private_ip
}

output "instance_id" {
  description = "OCID of the compute instance"
  value       = oci_core_instance.main.id
}

output "availability_domain" {
  description = "Availability domain where the instance was placed"
  value       = oci_core_instance.main.availability_domain
}

output "image_id" {
  description = "OCID of the OS image used"
  value       = data.oci_core_images.ubuntu_arm.images[0].id
}
