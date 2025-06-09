# Infrastructure as Code for Proprietary Trading Firm Platform

This repository contains all Infrastructure as Code (IaC) configurations for deploying and managing the Proprietary Trading Firm platform on AWS using Terraform.

## Project Structure

The repository is organized as follows:

- **`environments/`**: Contains environment-specific Terraform configurations (e.g., Staging, Production). Each environment will have its own `main.tf`, `variables.tf`, `outputs.tf`, and `terraform.tfvars` (for environment-specific values, excluded from Git if sensitive).
  - `staging/`
  - `production/`
- **`modules/`**: Contains reusable Terraform modules for provisioning various parts of the infrastructure (e.g., VPC, security groups, compute instances, databases, S3 buckets, monitoring components).
  - `vpc/`
  - `security/`
  - `iam/` (for resource-specific roles/policies)
  - `compute/`
  - `database/`
  - `s3/` (for application/service buckets)
  - `monitoring/`
  - `load_balancing/`
- **`global/`**: Contains Terraform configurations for global resources or resources not tied to a specific environment (e.g., global IAM users/groups, CI/CD pipeline roles, S3 bucket for Terraform state).
  - `iam/`
  - `s3/` (for Terraform state backend bucket configuration - though the bucket itself is created manually/via separate bootstrap)

## Terraform State Backend

Terraform state is managed remotely using AWS S3 with DynamoDB for state locking to ensure consistency and prevent conflicts.

- **S3 Bucket Name:** `prop-firm-terraform-state-<aws-account-id>-<region>` (Actual name will include specific account ID and region)
- **DynamoDB Table Name:** `prop-firm-terraform-state-lock` (Actual name will be specific)

Each environment (Staging, Production) will have its own state file within the S3 bucket under a unique key (e.g., `environments/staging/terraform.tfstate`).

## Usage

Detailed instructions on how to apply configurations for specific environments will be added here, typically involving:

1.  Navigating to the environment directory (e.g., `cd environments/staging`).
2.  Initializing Terraform (`terraform init`).
3.  Reviewing the execution plan (`terraform plan`).
4.  Applying the configuration (`terraform apply`).

These operations are primarily intended to be executed via the CI/CD pipeline.

## Contributing

[Details on contribution guidelines, branching strategy, and PR process will be added here.]
