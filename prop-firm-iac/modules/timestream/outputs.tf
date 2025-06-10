# modules/timestream/outputs.tf

output "database_name" {
  description = "The actual name of the Timestream database created (includes environment prefix)."
  value       = aws_timestreamwrite_database.main_db.database_name
}

output "database_arn" {
  description = "The ARN of the Timestream database."
  value       = aws_timestreamwrite_database.main_db.arn
}

output "table_details" {
  description = "Details of the created Timestream tables (logical key, actual table name, and ARN)."
  value = {
    for k, table_resource in aws_timestreamwrite_table.tables : k => {
      logical_name          = k # The key from the input map, e.g., "trades", "quotes_nbbo"
      actual_table_name     = table_resource.table_name
      table_arn             = table_resource.arn
      # The 'expected_dimensions' from the input variable can also be outputted for reference if useful
      expected_dimensions   = var.tables_config[k].expected_dimensions
    }
  }
}

output "table_arns" {
  description = "A map of table logical names (from tables_config map key) to their ARNs."
  value       = { for k, t in aws_timestreamwrite_table.tables : k => t.arn }
}

output "table_names" {
  description = "A map of table logical names (from tables_config map key) to their actual names in Timestream."
  value       = { for k, t in aws_timestreamwrite_table.tables : k => t.table_name }
}
