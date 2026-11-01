# OCI infrastructure

This Terraform configuration creates one public Ubuntu 24.04 aarch64 `VM.Standard.A1.Flex` instance, a small VCN/subnet, an Internet Gateway, and ingress for SSH, HTTP, and HTTPS. It uses Terraform's default local state; do not configure a remote backend or commit state files.

## Before applying

1. Install Terraform 1.6+ and configure an OCI API signing key for the intended tenancy.
2. Copy `terraform.tfvars.example` to `terraform.tfvars` and replace every example value. Git ignores the real file.
3. Select an Ubuntu 24.04 aarch64 image OCID for the selected OCI region and pin it in the local tfvars file. Image OCIDs are regional and change as Oracle publishes images.
4. Set `ssh_allowed_cidr` to the public IP/CIDR that should have SSH access, usually a `/32`. Do not leave SSH open to the whole Internet.
5. Keep the requested A1 size and boot volume within the account's current Always Free allowance. Capacity is not guaranteed; retry another availability domain only after reviewing the plan.

## Apply

```bash
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan
terraform -chdir=infra apply
terraform -chdir=infra output
```

Review the full plan before applying. To remove the VM and network when the assignment is over, run `terraform -chdir=infra destroy` and confirm the plan. Terraform does not install the newsroom application or agent API credentials; those are separate setup steps.
