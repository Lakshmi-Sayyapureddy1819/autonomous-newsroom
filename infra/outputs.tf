output "instance_name" {
  description = "Created OCI VM name."
  value       = oci_core_instance.newsroom.display_name
}

output "public_ip" {
  description = "Public IPv4 address. Open ports 80/443 in the OCI security list and use the deploy installer to configure Caddy."
  value       = data.oci_core_vnic.newsroom.public_ip_address
}

output "ssh_command" {
  description = "SSH command for the default Ubuntu image user."
  value       = "ssh ubuntu@${data.oci_core_vnic.newsroom.public_ip_address}"
}
