# modules/timestream/main.tf

locals {
  # Construct the full database name
  full_database_name = "${var.environment_name}-${var.database_name_suffix}"
}

resource "aws_timestreamwrite_database" "main_db" {
  database_name = local.full_database_name
  kms_key_id    = var.kms_key_id_for_database # Optional KMS key

  tags = merge(var.common_tags, {
    Name        = local.full_database_name
    Environment = var.environment_name
  })
}

resource "aws_timestreamwrite_table" "tables" {
  for_each = var.tables_config # Create a table for each entry in the map

  database_name = aws_timestreamwrite_database.main_db.database_name
  table_name    = each.value.table_name # Use the table_name specified in the config map value

  retention_properties {
    memory_store_retention_period_in_hours  = each.value.memory_store_retention_period_in_hours
    magnetic_store_retention_period_in_days = each.value.magnetic_store_retention_period_in_days
  }

  # Optional: Configure magnetic store writes. Default is enabled if magnetic retention > 0.
  # S3 rejected records location can be configured here if desired.
  # magnetic_store_write_properties {
  #   enable_magnetic_store_writes = true
  #   magnetic_store_rejected_data_location {
  #     s3_configuration {
  #       bucket_name = "your-timestream-rejected-records-bucket" # Needs to be created and passed in
  #       encryption_option = "SSE_S3"
  #     }
  #   }
  # }

  # Schema (Dimensions and Measures) in Timestream is defined by the data you write (schema-on-write).
  # The `aws_timestreamwrite_table` Terraform resource does not have a block to pre-define
  # dimensions and measures like some other database resources.
  # The `expected_dimensions` in `var.tables_config` is for documentation, consistency planning
  # with the DataWriter service, and potentially for generating fine-grained IAM policies if needed.
  # Timestream automatically creates dimensions and measures based on the first record written to the table.

  tags = merge(var.common_tags, {
    Name        = "${var.environment_name}-${aws_timestreamwrite_database.main_db.database_name}-${each.value.table_name}"
    Environment = var.environment_name
    ParentDB    = aws_timestreamwrite_database.main_db.database_name
    TableKey    = each.key # The logical key from the tables_config map (e.g., "trades", "quotes")
  })
}
